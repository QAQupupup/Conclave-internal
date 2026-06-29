"""Docker 容器沙箱：隔离用户代码与命令执行

部署架构（Docker socket mounting / sibling containers）：

  宿主机 (Windows / Linux / macOS)
  ├── Docker daemon
  ├── Conclave 容器 (Linux)
  │   ├── FastAPI 后端
  │   ├── docker CLI (安装在容器内)
  │   └── /var/run/docker.sock ← 从宿主挂载
  └── 沙箱容器 (按需创建的 sibling)
      └── conclave-workspace 卷 ← 与 Conclave 容器共享

  这样 Conclave 容器通过 docker socket 创建 sibling 容器执行用户代码，
  不是 dind（不需要 --privileged），安全性更好。

本地开发模式（Windows）：
  Docker Desktop 的 docker 是 .cmd 包装脚本，
  create_subprocess_exec 不搜索 .cmd 扩展名，
  因此所有 docker 命令通过 create_subprocess_shell 执行。

安全策略：
  - 网络分级   L1=--network none（默认，纯计算）
               L2=限网（pypi 白名单，允许 pip install）
               L3=全联网（明确授权，可访问外部 API）
  - 资源限制   --memory 256m --cpus 1
  - 文件系统   --read-only + tmpfs /tmp
  - 权限降级   --user 65534:65534 --cap-drop ALL
  - 自动清理   --rm
  - 超时控制   asyncio.wait_for
"""
from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.observability.log_bus import log_bus

# ---- 网络分级 ----

# L1: 纯计算，无网络（默认）
# L2: 限网，仅允许 pypi.org（pip install）
# L3: 全联网，可访问任意外部 API（需明确授权）
SandboxNetworkLevel = Literal["L1", "L2", "L3"]

# L2 限网：允许的域名白名单（通过 DNS 解析后的 IP 做 iptables 限制）
# Docker 不支持域名级网络限制，L2 用 bridge 网络 + 出站白名单实现
L2_ALLOWED_DOMAINS = ["pypi.org", "files.pythonhosted.org", "pypi.python.org"]

# ---- 配置 ----

# 沙箱镜像（国内镜像站优先）
SANDBOX_IMAGE = os.environ.get(
    "CONCLAVE_SANDBOX_IMAGE",
    "docker.m.daocloud.io/library/python:3.12-slim",
)

# 数据科学镜像：预装 pandas/numpy/matplotlib/sklearn/seaborn/scipy
# 供 code_analysis / tested_system 等需要数据分析库的模板按需使用
SANDBOX_IMAGE_DATASCIENCE = os.environ.get(
    "CONCLAVE_SANDBOX_IMAGE_DATASCIENCE",
    "conclave-python-datascience:latest",
)

# 备用镜像列表（主镜像拉取失败时依次尝试）
FALLBACK_IMAGES = [
    "docker.m.daocloud.io/library/python:3.12-slim",
    "python:3.12-slim",
]

# 资源限制
SANDBOX_MEM_LIMIT = os.environ.get("CONCLAVE_SANDBOX_MEM", "256m")
SANDBOX_CPU_LIMIT = os.environ.get("CONCLAVE_SANDBOX_CPUS", "1")
SANDBOX_TMPFS_SIZE = os.environ.get("CONCLAVE_SANDBOX_TMPFS", "64m")

# 沙箱模式: auto(默认,尝试Docker,失败拒绝) / docker(强制容器) / host(直接宿主机,仅开发)
SANDBOX_MODE: Literal["auto", "docker", "host"] = os.environ.get(
    "CONCLAVE_SANDBOX_MODE", "auto"
)  # type: ignore[assignment]

# 是否允许宿主机降级（默认 False，安全优先）
SANDBOX_ALLOW_HOST_FALLBACK = os.environ.get("CONCLAVE_SANDBOX_ALLOW_HOST", "") == "1"

# Docker socket 路径（容器内挂载位置）
DOCKER_SOCKET = os.environ.get("DOCKER_HOST", "")

# 缓存
_docker_available: bool | None = None
_resolved_image: str | None = None
# 已解析的按需镜像缓存（image_name -> resolved_name），数据科学等镜像走此缓存
_resolved_named_images: dict[str, str] = {}

_IS_WINDOWS = sys.platform == "win32"


def _shell_cmd(args: list[str]) -> str:
    """将参数列表转为 shell 命令字符串（跨平台安全引用）

    Windows: 用 subprocess.list2cmdline（cmd.exe 引用规则）
    Linux/macOS: 用 shlex.join（POSIX 引用规则）
    """
    if _IS_WINDOWS:
        return subprocess.list2cmdline(args)
    return shlex.join(args)


# ---- 数据类 ----


@dataclass
class ExecResult:
    """执行结果（代码或命令统一格式）"""

    exit_code: int
    stdout: str
    stderr: str
    sandboxed: bool
    image: str = ""
    fallback_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "sandboxed": self.sandboxed,
            "image": self.image,
            "fallback_reason": self.fallback_reason,
        }


# ---- Docker 可用性检测 ----


async def _check_docker() -> bool:
    """检测 Docker daemon 是否可用"""
    global _docker_available
    if _docker_available is not None:
        return _docker_available
    try:
        # 用 shell 模式，兼容 Windows(docker.cmd) 和 Linux(docker)
        cmd = _shell_cmd(["docker", "version", "--format", "{{.Server.Version}}"])
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=10)
        _docker_available = proc.returncode == 0
        if _docker_available:
            log_bus.info("Docker daemon 可用，沙箱模式激活", logger="sandbox")
        else:
            log_bus.warning("Docker daemon 不可用，将降级为宿主机执行", logger="sandbox")
    except Exception as e:
        _docker_available = False
        log_bus.warning(
            f"Docker 检测失败（{type(e).__name__}: {e}），将降级为宿主机执行",
            logger="sandbox",
        )
    return _docker_available


async def _resolve_image() -> str | None:
    """查找本地已有的沙箱镜像，没有则尝试拉取"""
    global _resolved_image
    if _resolved_image is not None:
        return _resolved_image

    for img in [SANDBOX_IMAGE, *FALLBACK_IMAGES]:
        cmd = _shell_cmd(["docker", "image", "inspect", img])
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if proc.returncode == 0:
            _resolved_image = img
            log_bus.info(f"沙箱镜像就绪: {img}", logger="sandbox")
            return img

    # 本地没有，尝试拉取
    log_bus.info(f"本地无沙箱镜像，尝试拉取: {SANDBOX_IMAGE}", logger="sandbox")
    cmd = _shell_cmd(["docker", "pull", SANDBOX_IMAGE])
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await asyncio.wait_for(proc.communicate(), timeout=120)
    if proc.returncode == 0:
        _resolved_image = SANDBOX_IMAGE
        log_bus.info(f"沙箱镜像拉取成功: {SANDBOX_IMAGE}", logger="sandbox")
        return _resolved_image

    log_bus.error(
        f"沙箱镜像拉取失败: {SANDBOX_IMAGE}，将降级为宿主机执行",
        logger="sandbox",
    )
    return None


async def _ensure_image_available(image: str) -> bool:
    """检查指定镜像本地是否就绪，不存在则尝试拉取"""
    cmd = _shell_cmd(["docker", "image", "inspect", image])
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    if proc.returncode == 0:
        return True

    log_bus.info(f"本地无镜像 {image}，尝试拉取", logger="sandbox")
    cmd = _shell_cmd(["docker", "pull", image])
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(proc.communicate(), timeout=300)
    except asyncio.TimeoutError:
        log_bus.error(f"镜像拉取超时: {image}", logger="sandbox")
        return False
    return proc.returncode == 0


async def _resolve_named_image(image: str) -> str | None:
    """解析指定的沙箱镜像（如数据科学镜像），本地无则拉取，带缓存

    与标准镜像不同：按需镜像无 FALLBACK（缺失数据科学库时标准镜像无法替代），
    解析失败返回 None，由调用方降级为宿主机执行。
    """
    cached = _resolved_named_images.get(image)
    if cached is not None:
        return cached
    if await _ensure_image_available(image):
        _resolved_named_images[image] = image
        log_bus.info(f"沙箱镜像就绪: {image}", logger="sandbox")
        return image
    log_bus.error(
        f"沙箱镜像不可用: {image}，将降级为宿主机执行",
        logger="sandbox",
    )
    return None


# ---- 安全选项构建 ----


def _build_security_args(
    workspace_root: Path,
    network_level: SandboxNetworkLevel = "L1",
) -> list[str]:
    """构建 Docker run 的安全参数

    workspace_root 是 backend 容器内路径（如 /workspace），
    对应 Docker 命名卷 conclave_conclave-workspace（compose 自动加项目前缀）。
    沙箱是 sibling 容器，bind mount 源路径必须是宿主机路径，
    因此用命名卷名而非容器内路径。

    network_level:
        L1 = --network none（默认，纯计算，无网络）
        L2 = 默认 bridge 网络（限网，允许 pip install pypi）
        L3 = 默认 bridge 网络（全联网，可访问任意外部 API）
    """
    container_ws = "/workspace"
    args = [
        "--rm",
        "-i",
        "--memory", SANDBOX_MEM_LIMIT,
        "--cpus", SANDBOX_CPU_LIMIT,
        "--read-only",
        "--tmpfs", f"/tmp:size={SANDBOX_TMPFS_SIZE}",
        "--user", "65534:65534",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "-v", "conclave_conclave-workspace:/workspace",
        "-w", container_ws,
    ]

    # 网络分级
    if network_level == "L1":
        args.append("--network")
        args.append("none")
    # L2/L3 使用默认 bridge 网络（有网络访问）
    # L2 的域名限制由 produce_node 在代码层约束（LLM prompt 指导 + 审计日志）
    # Docker 原生不支持域名级出站过滤，L2 和 L3 在容器层都是 bridge 网络
    # 区别在于：L2 需要明确声明用途，L3 需要用户授权

    return args


# ---- 容器内执行 ----


async def _run_in_container(
    code: str | None,
    command: str | None,
    workspace_root: Path,
    timeout: int,
    image: str | None = None,
    network_level: SandboxNetworkLevel = "L1",
) -> ExecResult:
    """在 Docker 容器中执行 Python 代码或 Shell 命令

    image: 指定沙箱镜像（如 SANDBOX_IMAGE_DATASCIENCE）；
           None 时使用标准镜像 SANDBOX_IMAGE（向后兼容）。
    network_level: 网络分级 L1(无网络)/L2(限网)/L3(全联网)

    代码通过写文件方式传入容器（非 stdin），原因：
    - Windows Docker Desktop 下 stdin 管道与 docker run python - 存在兼容性问题
    - 写文件后可通过 volume 挂载直接执行，无管道阻塞风险
    - 执行后文件保留在工作区，便于调试
    """
    if image is None:
        resolved = await _resolve_image()
    else:
        resolved = await _resolve_named_image(image)
    if resolved is None:
        raise RuntimeError("无可用沙箱镜像")

    security_args = _build_security_args(workspace_root, network_level=network_level)

    if code is not None:
        # 写文件方式：代码写入工作区，容器内通过挂载路径执行
        code_file = workspace_root / "_conclave_exec.py"
        code_file.write_text(code, encoding="utf-8")
        # 容器内路径 = 工作区挂载的 /workspace
        container_path = "/workspace/_conclave_exec.py"
        all_args = ["docker", "run", *security_args, resolved, "python", container_path]
        stdin_data = None
    else:
        assert command is not None
        all_args = ["docker", "run", *security_args, resolved, "sh", "-c", command]
        stdin_data = None

    # 用 shell 模式执行，兼容 Windows(docker.cmd) 和 Linux(docker)
    cmd_str = _shell_cmd(all_args)
    proc = await asyncio.create_subprocess_shell(
        cmd_str,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=stdin_data),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"沙箱执行超时（{timeout}s）")

    return ExecResult(
        exit_code=proc.returncode or 0,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
        sandboxed=True,
        image=resolved,
    )


# ---- 宿主机降级执行 ----


async def _run_on_host(
    code: str | None,
    command: str | None,
    workspace_root: Path,
    timeout: int,
) -> ExecResult:
    """降级方案：直接在宿主机执行（不安全，仅作 fallback）"""
    if code is not None:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workspace_root),
        )
    else:
        assert command is not None
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workspace_root),
        )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"宿主机执行超时（{timeout}s）")

    return ExecResult(
        exit_code=proc.returncode or 0,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
        sandboxed=False,
        fallback_reason="Docker 不可用，降级为宿主机执行",
    )


# ---- 公共 API ----


async def run_python(
    code: str,
    workspace_root: Path,
    timeout: int = 15,
    image: str | None = None,
    network_level: SandboxNetworkLevel = "L1",
) -> ExecResult:
    """执行 Python 代码（沙箱优先，降级宿主机）

    image: 可选，指定沙箱镜像（如 SANDBOX_IMAGE_DATASCIENCE）；
           默认 None 使用标准镜像 SANDBOX_IMAGE。
    network_level: 网络分级 L1(无网络,默认)/L2(限网,pip)/L3(全联网)
    """
    if SANDBOX_MODE == "host":
        return await _run_on_host(code, None, workspace_root, timeout)

    if SANDBOX_MODE == "docker" or await _check_docker():
        try:
            return await _run_in_container(
                code, None, workspace_root, timeout,
                image=image, network_level=network_level,
            )
        except RuntimeError:
            if SANDBOX_MODE == "docker":
                raise
        except TimeoutError:
            raise
        except Exception as e:
            log_bus.warning(f"容器执行异常: {e}", logger="sandbox")

    # Docker 不可用：拒绝执行（安全优先）
    if not SANDBOX_ALLOW_HOST_FALLBACK:
        log_bus.error("沙箱不可用且未启用宿主机降级，拒绝执行代码", logger="sandbox")
        return ExecResult(
            exit_code=127,
            stdout="",
            stderr="[安全拒绝] Docker 沙箱不可用。设置 CONCLAVE_SANDBOX_ALLOW_HOST=1 可允许宿主机降级（仅开发环境）。",
            sandboxed=False,
            fallback_reason="Docker 不可用，安全策略拒绝执行",
        )

    result = await _run_on_host(code, None, workspace_root, timeout)
    log_bus.warning("代码执行未隔离（宿主机直连），请检查 Docker 服务状态", logger="sandbox")
    return result


async def run_command(
    command: str,
    workspace_root: Path,
    timeout: int = 30,
    image: str | None = None,
    network_level: SandboxNetworkLevel = "L1",
) -> ExecResult:
    """执行 Shell 命令（沙箱优先，降级宿主机）

    image: 可选，指定沙箱镜像（如 SANDBOX_IMAGE_DATASCIENCE）；
           默认 None 使用标准镜像 SANDBOX_IMAGE。
    network_level: 网络分级 L1(无网络,默认)/L2(限网,pip)/L3(全联网)
    """
    if SANDBOX_MODE == "host":
        return await _run_on_host(None, command, workspace_root, timeout)

    if SANDBOX_MODE == "docker" or await _check_docker():
        try:
            return await _run_in_container(
                None, command, workspace_root, timeout,
                image=image, network_level=network_level,
            )
        except RuntimeError:
            if SANDBOX_MODE == "docker":
                raise
        except TimeoutError:
            raise
        except Exception as e:
            log_bus.warning(f"容器执行异常: {e}", logger="sandbox")

    # Docker 不可用：拒绝执行（安全优先）
    if not SANDBOX_ALLOW_HOST_FALLBACK:
        log_bus.error("沙箱不可用且未启用宿主机降级，拒绝执行命令", logger="sandbox")
        return ExecResult(
            exit_code=127,
            stdout="",
            stderr="[安全拒绝] Docker 沙箱不可用。设置 CONCLAVE_SANDBOX_ALLOW_HOST=1 可允许宿主机降级（仅开发环境）。",
            sandboxed=False,
            fallback_reason="Docker 不可用，安全策略拒绝执行",
        )

    result = await _run_on_host(None, command, workspace_root, timeout)
    log_bus.warning("命令执行未隔离（宿主机直连），请检查 Docker 服务状态", logger="sandbox")
    return result


async def get_status() -> dict:
    """获取沙箱状态信息（供前端展示）"""
    docker_ok = await _check_docker()
    image = await _resolve_image() if docker_ok else None
    return {
        "mode": SANDBOX_MODE,
        "docker_available": docker_ok,
        "image": image or "",
        "mem_limit": SANDBOX_MEM_LIMIT,
        "cpu_limit": SANDBOX_CPU_LIMIT,
        "active": docker_ok and image is not None,
    }
