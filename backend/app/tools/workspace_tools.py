"""Agent 工作区工具集：文件读写/命令执行/代码运行

供 ReAct 循环中的 Agent 自主调用，实现"能讨论 → 能动手"的能力升级。
所有工具函数接收 dict 参数，返回 dict 结果，统一适配 ToolRegistry.ToolFn 签名。

安全设计：
- 路径解析复用 workspace router 的 _resolve_path 逻辑（防目录穿越）
- 命令执行复用 sandbox.run_command（白名单检查 + Docker 沙箱隔离）
- 代码运行复用 sandbox.run_python（Docker 沙箱隔离）
- 工具接受 meeting_id 参数实现会议间文件隔离
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.config import settings
from app.middleware import is_dangerous_command
from app.observability.log_bus import log_bus
from app.sandbox import run_command as sandbox_run_command
from app.sandbox import run_python as sandbox_run_python

# ---- 配置 ----
WORKSPACE_ROOT = Path(settings.workspace_root).resolve()
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

CMD_TIMEOUT = int(os.environ.get("CONCLAVE_CMD_TIMEOUT", "30"))
CODE_TIMEOUT = int(os.environ.get("CONCLAVE_CODE_TIMEOUT", "15"))
MAX_OUTPUT = int(os.environ.get("CONCLAVE_MAX_OUTPUT", str(512 * 1024)))
MAX_FILE_READ = int(os.environ.get("CONCLAVE_MAX_FILE_READ", str(100 * 1024)))  # Agent读取文件上限100KB


def _resolve_path(rel_path: str, meeting_id: str | None = None) -> Path:
    """将相对路径解析为工作区内的绝对路径，防止目录穿越"""
    if meeting_id:
        meeting_dir = WORKSPACE_ROOT / meeting_id
        meeting_dir.mkdir(parents=True, exist_ok=True)
        base = meeting_dir
    else:
        base = WORKSPACE_ROOT

    if not rel_path:
        return base
    clean = rel_path.lstrip("/\\")
    target = (base / clean).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError(f"路径越界：{rel_path} 不在工作区内") from None
    return target


def _truncate(data: str, max_len: int = MAX_OUTPUT) -> str:
    if len(data.encode("utf-8")) > max_len:
        return data[:max_len] + "\n... [输出已截断]"
    return data


# ---- 文件系统工具 ----


async def tool_list_files(args: dict[str, Any]) -> dict[str, Any]:
    """列出工作区目录内容"""
    path = str(args.get("path", ""))
    meeting_id = args.get("meeting_id")
    try:
        target = _resolve_path(path, meeting_id)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    if not target.exists():
        return {"success": False, "error": f"路径不存在: {path}"}

    if target.is_file():
        stat = target.stat()
        return {
            "success": True,
            "path": path,
            "type": "file",
            "size": stat.st_size,
        }

    items = []
    for child in sorted(target.iterdir()):
        if child.name.startswith(".") or child.name == "__pycache__":
            continue
        try:
            stat = child.stat()
        except OSError:
            continue
        is_dir = child.is_dir()
        rel = str(child.relative_to(WORKSPACE_ROOT)).replace("\\", "/")
        items.append(
            {
                "name": child.name,
                "path": rel,
                "type": "directory" if is_dir else "file",
                "size": stat.st_size if not is_dir else 0,
            }
        )

    return {
        "success": True,
        "path": path or "/",
        "type": "directory",
        "items": items,
        "count": len(items),
    }


async def tool_read_file(args: dict[str, Any]) -> dict[str, Any]:
    """读取工作区文件内容"""
    path = str(args.get("path", ""))
    meeting_id = args.get("meeting_id")
    max_chars = int(args.get("max_chars", MAX_FILE_READ))

    if not path:
        return {"success": False, "error": "缺少 path 参数"}

    try:
        target = _resolve_path(path, meeting_id)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    if not target.exists():
        return {"success": False, "error": f"文件不存在: {path}"}
    if target.is_dir():
        return {"success": False, "error": f"路径是目录: {path}"}

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = target.read_bytes().decode("utf-8", errors="replace")
    except Exception as e:
        return {"success": False, "error": f"读取失败: {e}"}

    truncated = len(content) > max_chars
    content = content[:max_chars]

    return {
        "success": True,
        "path": path,
        "content": content,
        "size": target.stat().st_size,
        "truncated": truncated,
    }


async def tool_write_file(args: dict[str, Any]) -> dict[str, Any]:
    """写入文件（自动创建父目录）"""
    path = str(args.get("path", ""))
    content = str(args.get("content", ""))
    meeting_id = args.get("meeting_id")

    if not path:
        return {"success": False, "error": "缺少 path 参数"}

    try:
        target = _resolve_path(path, meeting_id)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        target.write_text(content, encoding="utf-8")
    except Exception as e:
        return {"success": False, "error": f"写入失败: {e}"}

    log_bus.info(
        f"[Agent工具] 文件写入: {path} ({len(content)} chars)",
        logger="tools.workspace",
        extra={"path": path, "size": len(content), "meeting_id": meeting_id},
    )

    return {
        "success": True,
        "path": path,
        "size": len(content),
        "saved": True,
    }


# ---- 命令执行工具 ----


async def tool_run_command(args: dict[str, Any]) -> dict[str, Any]:
    """在沙箱中执行 Shell 命令"""
    command = str(args.get("command", ""))
    meeting_id = args.get("meeting_id")
    cwd = str(args.get("cwd", ""))
    network_level = str(args.get("network_level", "L2"))
    timeout = int(args.get("timeout", CMD_TIMEOUT))

    if not command:
        return {"success": False, "error": "缺少 command 参数"}

    # 安全检查
    if is_dangerous_command(command):
        return {
            "success": False,
            "error": "命令被安全策略阻止：检测到危险命令模式（如 rm -rf /、mkfs、dd 等）",
        }

    # 确定工作目录（会议隔离）
    if meeting_id:
        work_dir = _resolve_path(cwd, meeting_id) if cwd else _resolve_path("", meeting_id)
    else:
        work_dir = _resolve_path(cwd) if cwd else WORKSPACE_ROOT

    log_bus.info(
        f"[Agent工具] 执行命令: {command}",
        logger="tools.workspace",
        extra={"command": command[:200], "meeting_id": meeting_id},
    )

    try:
        result = await sandbox_run_command(
            command,
            work_dir,
            timeout,
            network_level=network_level,  # type: ignore[arg-type]
        )
    except TimeoutError:
        return {"success": False, "error": f"命令执行超时（{timeout}s）"}
    except Exception as e:
        return {"success": False, "error": f"执行失败: {e}"}

    return {
        "success": result.exit_code == 0,
        "exit_code": result.exit_code,
        "stdout": _truncate(result.stdout),
        "stderr": _truncate(result.stderr),
        "sandboxed": result.sandboxed,
        "image": result.image,
    }


async def tool_run_python(args: dict[str, Any]) -> dict[str, Any]:
    """在沙箱中执行 Python 代码"""
    code = str(args.get("code", ""))
    meeting_id = args.get("meeting_id")
    network_level = str(args.get("network_level", "L1"))
    timeout = int(args.get("timeout", CODE_TIMEOUT))

    if not code:
        return {"success": False, "error": "缺少 code 参数"}

    work_dir = _resolve_path("", meeting_id) if meeting_id else WORKSPACE_ROOT

    log_bus.info(
        f"[Agent工具] 执行Python代码: {len(code)} chars",
        logger="tools.workspace",
        extra={"code_len": len(code), "meeting_id": meeting_id},
    )

    try:
        result = await sandbox_run_python(
            code,
            work_dir,
            timeout,
            network_level=network_level,  # type: ignore[arg-type]
        )
    except TimeoutError:
        return {"success": False, "error": f"代码执行超时（{timeout}s）"}
    except Exception as e:
        return {"success": False, "error": f"执行失败: {e}"}

    return {
        "success": result.exit_code == 0,
        "exit_code": result.exit_code,
        "stdout": _truncate(result.stdout),
        "stderr": _truncate(result.stderr),
        "sandboxed": result.sandboxed,
        "image": result.image,
    }


async def tool_install_package(args: dict[str, Any]) -> dict[str, Any]:
    """安装 Python 包（pip install，L2限网模式）"""
    package = str(args.get("package", ""))
    meeting_id = args.get("meeting_id")

    if not package:
        return {"success": False, "error": "缺少 package 参数"}

    # 安全检查：只允许包名，不允许额外参数（防注入）
    import re

    if not re.match(r"^[a-zA-Z0-9_\-][a-zA-Z0-9_\-.=<>~!,\[\]]*$", package):
        return {"success": False, "error": f"无效的包名: {package}"}

    command = f"pip install {package}"
    return await tool_run_command(
        {
            "command": command,
            "meeting_id": meeting_id,
            "network_level": "L2",
            "timeout": 120,
        }
    )


def register_workspace_tools(registry: Any) -> None:
    """将工作区工具注册到 ToolRegistry"""
    registry.register(
        "fs.list",
        "列出工作区目录中的文件和子目录。返回文件名、类型（file/directory）、大小。"
        "不指定 path 时列出根目录。用于探索项目结构。",
        tool_list_files,
        {
            "path": "str（可选，目录路径，默认根目录）",
            "meeting_id": "str（会议ID，自动注入）",
        },
    )

    registry.register(
        "fs.read",
        "读取工作区中文件的内容。返回文件文本内容（UTF-8编码）。用于查看已有代码、配置文件、输出结果等。",
        tool_read_file,
        {
            "path": "str（必填，文件相对路径，如 'src/main.py'）",
            "meeting_id": "str（会议ID，自动注入）",
            "max_chars": "int（可选，最大读取字符数，默认100000）",
        },
    )

    registry.register(
        "fs.write",
        "创建或覆盖写入文件。自动创建不存在的父目录。用于创建代码文件、配置文件、保存输出结果等。",
        tool_write_file,
        {
            "path": "str（必填，文件相对路径，如 'src/main.py'）",
            "content": "str（必填，文件内容）",
            "meeting_id": "str（会议ID，自动注入）",
        },
    )

    registry.register(
        "shell.exec",
        "在沙箱中执行 Shell 命令。命令在 Docker 容器中隔离执行（默认网络受限）。"
        "用于运行构建命令、测试、查看文件状态、git操作等。危险命令会被安全策略阻止。",
        tool_run_command,
        {
            "command": "str（必填，要执行的命令，如 'ls -la', 'python -m pytest', 'npm run build'）",
            "cwd": "str（可选，工作目录，相对于工作区根目录）",
            "network_level": "str（可选，网络级别：L1=无网络(默认), L2=限网(pip install), L3=全联网）",
            "timeout": "int（可选，超时秒数，默认30）",
            "meeting_id": "str（会议ID，自动注入）",
        },
    )

    registry.register(
        "python.run",
        "在沙箱中执行 Python 代码片段。代码在 Docker 容器中隔离执行（默认无网络）。"
        "工作目录自动挂载到容器中，可以读写工作区文件。用于数据处理、计算、验证代码逻辑等。",
        tool_run_python,
        {
            "code": "str（必填，要执行的 Python 代码）",
            "network_level": "str（可选，网络级别：L1=无网络(默认), L2=限网(pip), L3=全联网）",
            "timeout": "int（可选，超时秒数，默认15）",
            "meeting_id": "str（会议ID，自动注入）",
        },
    )

    registry.register(
        "pip.install",
        "安装 Python 依赖包（pip install）。在限网沙箱中执行，只允许从 PyPI 安装。用于运行代码前安装需要的第三方库。",
        tool_install_package,
        {
            "package": "str（必填，包名，如 'requests', 'pandas>=2.0', 'flask==3.0'）",
            "meeting_id": "str（会议ID，自动注入）",
        },
    )
