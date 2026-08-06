# 工作区路由：文件读写 / 目录列表 / 命令执行 / 代码运行
# 让 Conclave 从"讨论代码"升级为"能生成 + 能运行 + 能看结果"
# 安全：路径沙盒限制 + 命令超时 + 输出大小截断
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.middleware import is_dangerous_command
from app.observability.log_bus import log_bus
from app.sandbox import get_status as sandbox_status
from app.sandbox import run_command, run_python
from app.schemas.workspace import CodeRunRequest, CommandRequest, FileWriteRequest

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
        ) from None
    return target


async def _validate_tenant_path_access(rel_path: str) -> None:
    """[Wave 2] 验证文件路径对应的会议属于当前租户。

    从路径中提取第一段作为 meeting_id（如 "mtg-xxx/app.py" → "mtg-xxx"），
    通过 DAO 验证该会议属于当前租户。系统租户跳过验证。

    - 空路径（根目录列表）：系统租户允许，普通租户允许（后续 list_files 会过滤）
    - 路径首段为 meeting_id：验证归属
    - 会议不存在或不属于当前租户：403
    """
    from app.tenants.context import is_system_tenant

    if is_system_tenant():
        return

    if not rel_path:
        return  # 根目录列表，后续在 list_files 中过滤

    # 提取第一段作为 meeting_id
    clean = rel_path.lstrip("/\\")
    parts = clean.split("/", 1)
    if "\\" in parts[0]:
        parts = parts[0].split("\\", 1) + parts[1:]
    meeting_id = parts[0]

    # 如果不是 meeting_id 格式（不以 mtg- 开头），跳过验证（可能是其他用途的文件）
    if not meeting_id.startswith("mtg-"):
        return

    from app.dao.meeting_dao import get_meeting

    meeting = await get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(
            status_code=403,
            detail="无权访问该会议的工作区文件",
        )


def _truncate(data: str) -> str:
    """截断超长输出"""
    if len(data.encode("utf-8")) > MAX_OUTPUT:
        return data[:MAX_OUTPUT] + "\n... [输出已截断]"
    return data


# ---- 文件操作 ----


@router.get("/files")
async def list_files(path: str = "") -> dict[str, Any]:
    """列出工作区内指定目录的文件和子目录"""
    await _validate_tenant_path_access(path)
    target = _resolve_path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"路径不存在: {path}")
    if target.is_file():
        # 单个文件：返回统一结构，将文件包装在 items 中，避免前端解构出错
        import os

        stat = target.stat()
        filename = os.path.basename(path)
        parent_path = os.path.dirname(path).replace("\\", "/")
        return {
            "path": parent_path or "/",
            "type": "directory",
            "items": [
                {
                    "name": filename,
                    "path": path.replace("\\", "/"),
                    "type": "file",
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    "child_count": 0,
                    "expanded": False,
                }
            ],
        }

    items = []
    # [Wave 2] 根目录列表：非系统租户只显示属于自己的会议目录
    from app.tenants.context import is_system_tenant

    _is_root_listing = target == WORKSPACE_ROOT
    _tenant_meeting_ids: set[str] | None = None
    _meeting_topics: dict[str, str] = {}
    if _is_root_listing:
        from app.dao.meeting_dao import list_meetings

        meetings = await list_meetings()
        _meeting_topics = {m["id"]: m.get("topic", "") for m in meetings}
        if not is_system_tenant():
            _tenant_meeting_ids = {m["id"] for m in meetings}

    for child in sorted(target.iterdir()):
        # 跳过隐藏文件和 __pycache__
        if child.name.startswith(".") or child.name == "__pycache__":
            continue
        # [Wave 2] 根目录列表过滤：跳过不属于当前租户的会议目录
        if _tenant_meeting_ids is not None and child.is_dir() and child.name not in _tenant_meeting_ids:
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

        # 会议目录显示名：mtg-xxx → 会议主题；孤立目录显示缩短 ID
        display_name: str | None = None
        if is_dir and child.name.startswith("mtg-"):
            if _meeting_topics.get(child.name):
                topic = _meeting_topics[child.name].replace("\n", " ").replace("\r", " ").strip()
                display_name = topic if len(topic) <= 30 else f"{topic[:28]}…"
            else:
                # 孤立目录（数据库中无对应会议）：显示缩短 ID
                short_id = child.name[4:12] if len(child.name) > 12 else child.name[4:]
                display_name = f"会议 {short_id}"

        items.append(
            {
                "name": child.name,
                "display_name": display_name,
                "path": str(child.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
                "type": "directory" if is_dir else "file",
                "size": stat.st_size if not is_dir else 0,
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "child_count": child_count,
                "children_count": child_count,
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
    await _validate_tenant_path_access(file_path)
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
        raise HTTPException(status_code=500, detail=f"读取失败: {e}") from e

    return {
        "path": file_path,
        "content": _truncate(content),
        "size": target.stat().st_size,
        "language": _detect_language(target.suffix),
    }


@router.post("/files")
async def write_file(req: FileWriteRequest) -> dict[str, Any]:
    """写入文件（自动创建父目录）"""
    await _validate_tenant_path_access(req.path)
    target = _resolve_path(req.path)
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        target.write_text(req.content, encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入失败: {e}") from e

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
async def delete_file(file_path: str, request: Request, cascade: bool = False) -> dict[str, Any]:
    """删除文件或目录

    - cascade=false（默认）：仅删除文件或空目录
    - cascade=true：级联删除目录及其所有内容（适用于清理会议工作区等场景）

    权限要求：
    - 系统管理员（system_admin/system_owner/admin）可删除任意路径
    - 会议目录（mtg-*）下的文件：需为会议创建者、Team owner 或 maintainer
    - 根目录文件：仅系统管理员可删除
    """
    await _validate_tenant_path_access(file_path)
    target = _resolve_path(file_path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"路径不存在: {file_path}")

    # 权限校验：从路径中提取 meeting_id，检查删除权限
    from app.auth_guard import assert_can_delete_meeting, get_current_user, is_admin

    _uid, _username, role = get_current_user(request)
    admin_mode = is_admin(role)

    if not admin_mode:
        # 提取路径首段作为 meeting_id
        clean = file_path.lstrip("/\\")
        parts = clean.split("/", 1)
        if "\\" in parts[0]:
            parts = parts[0].split("\\", 1) + parts[1:]
        meeting_id = parts[0] if parts else ""

        if meeting_id.startswith("mtg-"):
            # 会议目录下的文件：校验会议删除权限
            from app.dao.meeting_dao import get_meeting

            meeting = await get_meeting(meeting_id)
            if meeting is None:
                raise HTTPException(status_code=403, detail="无权删除该会议工作区文件")
            await assert_can_delete_meeting(request, meeting)
        else:
            # 根目录文件：仅系统管理员可删除
            raise HTTPException(status_code=403, detail="仅系统管理员可删除根目录文件")

    try:
        if target.is_file():
            target.unlink()
        elif target.is_dir():
            if cascade:
                shutil.rmtree(target)
            else:
                # 只允许删除空目录
                target.rmdir()
    except OSError as e:
        import errno as _errno

        if e.errno == _errno.ENOTEMPTY:
            msg = "文件夹不为空，请使用级联删除（cascade=true）删除包含内容的文件夹"
        else:
            msg = f"删除失败: {e}"
        raise HTTPException(status_code=400, detail=msg) from e

    log_bus.info(
        f"文件删除: {file_path} (cascade={cascade})",
        logger="routers.workspace",
    )
    return {"path": file_path, "deleted": True, "cascade": cascade}


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
            req.command,
            WORKSPACE_ROOT,
            CMD_TIMEOUT,
            network_level=req.network_level,  # type: ignore[arg-type]
        )
    except TimeoutError as e:
        raise HTTPException(status_code=408, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"执行失败: {e}") from e

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
            req.code,
            WORKSPACE_ROOT,
            CODE_TIMEOUT,
            network_level=req.network_level,  # type: ignore[arg-type]
        )
    except TimeoutError as e:
        raise HTTPException(status_code=408, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"执行失败: {e}") from e

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
