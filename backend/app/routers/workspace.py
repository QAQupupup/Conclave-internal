# 工作区路由：文件读写 / 目录列表 / 命令执行 / 代码运行
# 让 Conclave 从"讨论代码"升级为"能生成 + 能运行 + 能看结果"
# 安全：路径沙盒限制 + 命令超时 + 输出大小截断
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.middleware import is_dangerous_command
from app.observability.log_bus import log_bus
from app.sandbox import run_command, run_python, get_status as sandbox_status

router = APIRouter(prefix="/workspace", tags=["workspace"])

# ---- 安全配置 ----

# 工作区根目录：使用 config.settings 中的 workspace_root（与 produce_node 写入路径一致）
WORKSPACE_ROOT = Path(settings.workspace_root).resolve()
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

# 命令执行超时（秒）
CMD_TIMEOUT = int(os.environ.get("CONCLAVE_CMD_TIMEOUT", "30"))
# 代码运行超时（秒）
CODE_TIMEOUT = int(os.environ.get("CONCLAVE_CODE_TIMEOUT", "15"))
# 输出最大字节数（防止超大输出撑爆前端）
MAX_OUTPUT = int(os.environ.get("CONCLAVE_MAX_OUTPUT", str(512 * 1024)))

# 禁止执行的命令模式（安全检查）由 app.middleware.is_dangerous_command 提供。


def _resolve_path(rel_path: str, meeting_id: str | None = None) -> Path:
    """将相对路径解析为工作区内的绝对路径，防止目录穿越攻击。

    若提供 meeting_id，则路径解析到 WORKSPACE_ROOT/meeting_id/ 子目录下，
    实现会议间文件隔离。回退兼容：若 meeting_id 子目录不存在，自动创建。
    """
    if meeting_id:
        # 会议隔离模式：所有路径限定在 WORKSPACE_ROOT/meeting_id/ 下
        meeting_dir = WORKSPACE_ROOT / meeting_id
        meeting_dir.mkdir(parents=True, exist_ok=True)
        base = meeting_dir
    else:
        base = WORKSPACE_ROOT

    if not rel_path:
        return base
    # 去掉前导斜杠，强制相对
    clean = rel_path.lstrip("/\\")
    target = (base / clean).resolve()
    # 安全检查：目标必须在 base 内
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(
            status_code=403,
            detail=f"路径越界：{rel_path} 不在工作区内",
        )
    return target


def _truncate(data: str) -> str:
    """截断超长输出"""
    if len(data.encode("utf-8")) > MAX_OUTPUT:
        return data[:MAX_OUTPUT] + "\n... [输出已截断]"
    return data


# ---- 请求/响应模型 ----


class FileWriteRequest(BaseModel):
    path: str = Field(..., description="工作区内相对路径")
    content: str = Field(..., description="文件内容")


class CodeRunRequest(BaseModel):
    code: str = Field(..., description="要执行的 Python 代码")
    language: str = Field(default="python", description="语言（目前支持 python）")
    network_level: str = Field(default="L1", description="网络分级：L1=无网络(默认) / L2=限网(pip) / L3=全联网")


class CommandRequest(BaseModel):
    command: str = Field(..., description="要执行的命令")
    cwd: str = Field(default="", description="工作目录（工作区内相对路径）")
    network_level: str = Field(default="L2", description="网络分级：L1=无网络 / L2=限网(默认,pip) / L3=全联网")


# ---- 文件操作 ----


@router.get("/files")
async def list_files(path: str = "") -> dict[str, Any]:
    """列出工作区内指定目录的文件和子目录"""
    target = _resolve_path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"路径不存在: {path}")
    if target.is_file():
        # 单个文件：返回元信息
        stat = target.stat()
        return {
            "path": path,
            "type": "file",
            "size": stat.st_size,
            "modified": stat.st_mtime,
        }

    items = []
    for child in sorted(target.iterdir()):
        # 跳过隐藏文件和 __pycache__
        if child.name.startswith(".") or child.name == "__pycache__":
            continue
        try:
            stat = child.stat()
        except OSError:
            continue
        is_dir = child.is_dir()
        # [CON-11 修复] 子节点计数：递归树渲染需要预知目录是否可展开
        # 旧版客户端只展示一层目录，要看到内嵌结构需多次请求
        child_count = 0
        if is_dir:
            try:
                child_count = sum(1 for c in child.iterdir() if not c.name.startswith(".") and c.name != "__pycache__")
            except OSError:
                child_count = 0
        items.append(
            {
                "name": child.name,
                "path": str(child.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
                "type": "directory" if is_dir else "file",
                "size": stat.st_size if not is_dir else 0,
                "modified": stat.st_mtime,
                "child_count": child_count,
                "expanded": False,
            }
        )
    return {
        "path": path or "/",
        "type": "directory",
        "items": items,
    }


@router.get("/files/{file_path:path}")
async def read_file(file_path: str) -> dict[str, Any]:
    """读取工作区内文件内容"""
    target = _resolve_path(file_path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_path}")
    if target.is_dir():
        raise HTTPException(status_code=400, detail=f"路径是目录: {file_path}")

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = target.read_bytes().decode("utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取失败: {e}")

    return {
        "path": file_path,
        "content": _truncate(content),
        "size": target.stat().st_size,
        "language": _detect_language(target.suffix),
    }


@router.post("/files")
async def write_file(req: FileWriteRequest) -> dict[str, Any]:
    """写入文件（自动创建父目录）"""
    target = _resolve_path(req.path)
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        target.write_text(req.content, encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入失败: {e}")

    log_bus.info(
        f"文件写入: {req.path} ({len(req.content)} chars)",
        logger="routers.workspace",
        extra={"path": req.path, "size": len(req.content)},
    )

    return {
        "path": req.path,
        "size": len(req.content),
        "saved": True,
    }


@router.delete("/files/{file_path:path}")
async def delete_file(file_path: str) -> dict[str, Any]:
    """删除文件或空目录"""
    target = _resolve_path(file_path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"路径不存在: {file_path}")

    try:
        if target.is_file():
            target.unlink()
        elif target.is_dir():
            # 只允许删除空目录
            target.rmdir()
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"删除失败: {e}")

    log_bus.info(f"文件删除: {file_path}", logger="routers.workspace")
    return {"path": file_path, "deleted": True}


# ---- 命令执行 ----


@router.post("/exec")
async def exec_command(req: CommandRequest) -> dict[str, Any]:
    """在工作区内执行命令（沙箱优先，降级宿主机）"""
    # 安全检查：危险命令模式检测
    if is_dangerous_command(req.command):
        raise HTTPException(
            status_code=403,
            detail="命令被安全策略阻止：检测到危险命令模式",
        )

    log_bus.info(
        f"执行命令: {req.command}",
        logger="routers.workspace",
        extra={"command": req.command},
    )

    try:
        result = await run_command(
            req.command, WORKSPACE_ROOT, CMD_TIMEOUT,
            network_level=req.network_level,  # type: ignore[arg-type]
        )
    except TimeoutError as e:
        raise HTTPException(status_code=408, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"执行失败: {e}")

    return {
        "command": req.command,
        "exit_code": result.exit_code,
        "stdout": _truncate(result.stdout),
        "stderr": _truncate(result.stderr),
        "sandboxed": result.sandboxed,
        "image": result.image,
        "fallback_reason": result.fallback_reason,
        "duration_hint": f"<{CMD_TIMEOUT}s",
    }


# ---- 代码运行 ----


@router.post("/run")
async def run_code(req: CodeRunRequest) -> dict[str, Any]:
    """执行 Python 代码片段（沙箱优先，降级宿主机）"""
    if req.language != "python":
        raise HTTPException(
            status_code=400,
            detail=f"不支持的语言: {req.language}（目前仅支持 python）",
        )

    log_bus.info(
        f"执行代码: {len(req.code)} chars",
        logger="routers.workspace",
        extra={"language": req.language, "code_len": len(req.code)},
    )

    try:
        result = await run_python(
            req.code, WORKSPACE_ROOT, CODE_TIMEOUT,
            network_level=req.network_level,  # type: ignore[arg-type]
        )
    except TimeoutError as e:
        raise HTTPException(status_code=408, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"执行失败: {e}")

    return {
        "language": req.language,
        "exit_code": result.exit_code,
        "stdout": _truncate(result.stdout),
        "stderr": _truncate(result.stderr),
        "sandboxed": result.sandboxed,
        "image": result.image,
        "fallback_reason": result.fallback_reason,
        "duration_hint": f"<{CODE_TIMEOUT}s",
    }


# ---- 工作区信息 ----


@router.get("/info")
async def workspace_info() -> dict[str, Any]:
    """返回工作区配置信息"""
    return {
        "root": str(WORKSPACE_ROOT),
        "exists": WORKSPACE_ROOT.exists(),
        "cmd_timeout": CMD_TIMEOUT,
        "code_timeout": CODE_TIMEOUT,
        "max_output": MAX_OUTPUT,
        "python": sys.executable,
        "python_version": sys.version.split()[0],
        "sandbox": await sandbox_status(),
    }


@router.get("/sandbox/status")
async def sandbox_info() -> dict[str, Any]:
    """返回沙箱状态（供前端展示当前执行模式）"""
    return await sandbox_status()


# ---- 辅助函数 ----


def _detect_language(suffix: str) -> str:
    """根据文件扩展名推断语言"""
    mapping = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".jsx": "jsx",
        ".json": "json",
        ".md": "markdown",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".html": "html",
        ".css": "css",
        ".sh": "shell",
        ".sql": "sql",
        ".xml": "xml",
        ".txt": "text",
    }
    return mapping.get(suffix.lower(), "text")
