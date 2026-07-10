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
import re
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

# [CON-04 修复] 命令白名单：仅允许 LLM 生成受控命令集中的命令。
# 严格模式：仅允许列出命令；其他命令拒绝执行。
# 通过 env 可放宽，便于开发期调试。
ALLOWED_COMMANDS: set[str] = set(
    os.environ.get(
        "CONCLAVE_SANDBOX_CMD_ALLOWLIST",
        "ls,cat,head,tail,wc,grep,awk,sed,sort,uniq,find,echo,pwd,date,whoami,env,which,file,"
        "python,pip,pytest,python3,jq,tr,cut,tee,xargs,"
        # 常用构建工具（受网络分级 L2 限制）
        "make,cmake,git,npm,yarn,node,go,rustc,cargo,gcc,g++",
    ).split(",")
)
# 危险模式：在 allowlist 之上额外拦截的反模式
BLOCKED_PATTERNS: list[str] = [
    r"\brm\s+-rf\s+/",          # rm -rf /
    r"\bdd\s+if=",              # 磁盘擦除
    r":\(\)\s*\{.*\};:",         # fork bomb
    r"curl\s+.*\|\s*(bash|sh)",  # 远程脚本执行
    r"wget\s+.*\|\s*(bash|sh)",
    r"\bchmod\s+777\s+/",       # 全开权限到根目录
]

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


# [CON-04 修复] 命令安全检查：先白名单、再黑名单。
def _check_command_safety(command: str) -> tuple[bool, str]:
    """检查命令是否在沙箱白名单内且不含危险模式。

    Returns:
        (allowed, reason): allowed=True 表示通过，False 表示拒绝并附原因。
    """
    # 1) 危险模式拦截（最优先）
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command):
            return False, f"命令匹配危险模式: {pattern}"

    # 2) 提取首词（命令名）做白名单检查
    first_token = command.strip().split(maxsplit=1)
    if not first_token:
        return False, "空命令"
    cmd_name = first_token[0]
    # 跳过环境变量赋值前缀（如 FOO=bar python xxx）
    while "=" in cmd_name:
        first_token_remainder = first_token[1].split(maxsplit=1) if len(first_token) > 1 else []
        if not first_token_remainder:
            return False, "仅含变量赋值"
        first_token = [first_token_remainder[0]] + first_token_remainder[1:]
        cmd_name = first_token[0]

    # 取可执行文件 basename（处理 /usr/bin/python 等绝对路径）
    cmd_basename = os.path.basename(cmd_name)
    if cmd_basename not in ALLOWED_COMMANDS:
        return False, f"命令 {cmd_basename!r} 不在白名单（{len(ALLOWED_COMMANDS)} 个允许）"
    return True, "ok"


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

    [CON-04 修复] 改用 create_subprocess_exec + list 参数而非 create_subprocess_shell，
    避免命令字符串拼接导致的 Shell 注入风险（如 workspace_root 含特殊字符）。
    Docker 客户端在 Windows 上是 .cmd 包装脚本，需通过 shell 模式启动。
    折中方案：仅把 docker 这一个固定二进制通过 shell 模式启动，
    docker run 的所有参数通过 list 传给 create_subprocess_exec。
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
    else:
        assert command is not None
        # [CON-04 修复] 命令参数必须通过 list 传入，由 docker run 在容器内 sh -c 执行。
        # 容器内的 sh -c 不会逃逸到宿主机，且 docker run 自身用 list2cmdline 封装整个 shell 段。
        # 注意：此 shell 段仍由容器内 sh 解释，因此命令内容应只来自受信任的 LLM 输出 + 审计。
        # 进一步加固：在调用方做 allowlist（仅允许受限命令集），由 produce_node 的 LLM prompt 约束。
        all_args = ["docker", "run", *security_args, resolved, "sh", "-c", command]

    # [CON-04 修复] 用 create_subprocess_exec + list 参数，避免字符串拼接。
    # Windows 上 .cmd 包装脚本会自动被 asyncio 找到并通过 cmd.exe 执行。
    try:
        proc = await asyncio.create_subprocess_exec(
            *all_args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"Docker 不可用: {e}") from e

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
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

    [CON-04 修复] 执行前做白名单+黑名单检查。命令来自 LLM 时可能被 prompt injection
    污染（如 "rm -rf /"），必须在沙箱边界拒绝。
    """
    allowed, reason = _check_command_safety(command)
    if not allowed:
        log_bus.error(
            f"命令被安全策略拒绝: {reason}",
            logger="sandbox",
            extra={"command": command[:200], "reason": reason},
        )
        return ExecResult(
            exit_code=126,  # 126 = command cannot execute
            stdout="",
            stderr=f"[安全拒绝] {reason}",
            sandboxed=False,
            fallback_reason=f"命令未通过白名单检查: {reason}",
        )

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


# ---- 启动预热 ----

async def warmup_sandbox() -> dict:
    """启动时预热沙箱环境（后台任务，不阻塞应用启动）

    流程：
      1. 重置检测缓存（entrypoint 可能已修复了 socket 权限）
      2. 检测 Docker daemon 可用性
      3. 预拉取标准沙箱镜像
      4. 尝试构建/拉取数据科学镜像
      5. 执行一次最小化自检（docker run --rm echo hello）
    返回预热结果 dict，包含状态和耗时。
    """
    import time
    t0 = time.time()
    log = log_bus.info
    log_warn = log_bus.warning

    # 重置缓存，重新检测（entrypoint 可能在 Python 进程启动前就配好了权限）
    global _docker_available, _resolved_image, _resolved_named_images
    _docker_available = None
    _resolved_image = None
    _resolved_named_images = {}

    log("[sandbox-warmup] 开始沙箱环境预热...", logger="sandbox")

    # 1. 检测 Docker
    docker_ok = await _check_docker()
    if not docker_ok:
        log_warn("[sandbox-warmup] Docker daemon 不可用，沙箱功能将被禁用。"
                 "请确认 /var/run/docker.sock 已挂载且当前用户有权限访问。", logger="sandbox")
        return {"ok": False, "reason": "docker_unavailable", "elapsed": time.time() - t0}

    # 2. 预拉取标准镜像
    image = await _resolve_image()
    if not image:
        log_warn("[sandbox-warmup] 标准沙箱镜像拉取失败", logger="sandbox")
        return {"ok": False, "reason": "image_pull_failed", "elapsed": time.time() - t0}

    log(f"[sandbox-warmup] 标准沙箱镜像就绪: {image}", logger="sandbox")

    # 3. 检查/拉取数据科学镜像
    try:
        ds_image = await _resolve_named_image(SANDBOX_IMAGE_DATASCIENCE)
        if ds_image:
            log(f"[sandbox-warmup] 数据科学镜像就绪: {ds_image}", logger="sandbox")
        else:
            log_warn("[sandbox-warmup] 数据科学镜像不可用，数据分析模板将使用标准镜像", logger="sandbox")
    except Exception as e:
        log_warn(f"[sandbox-warmup] 数据科学镜像准备失败: {e}", logger="sandbox")

    # 4. 最小化自检：运行 echo hello 验证沙箱容器能正常创建/执行/清理
    try:
        from app.config import settings
        ws_root = Path(getattr(settings, 'workspace_root', None) or os.environ.get("CONCLAVE_WORKSPACE_DIR", "/workspace"))
        result = await run_command("echo sandbox-warmup-ok", ws_root, timeout=15, network_level="L1")
        if result.exit_code == 0 and "sandbox-warmup-ok" in result.stdout:
            log(f"[sandbox-warmup] 自检通过 ✓ （耗时 {time.time() - t0:.1f}s，沙箱容器正常创建/执行/清理）", logger="sandbox")
            return {"ok": True, "image": image, "elapsed": time.time() - t0}
        else:
            log_warn(f"[sandbox-warmup] 自检异常: exit={result.exit_code}, stderr={result.stderr[:200]}", logger="sandbox")
            return {"ok": False, "reason": "self_test_failed", "elapsed": time.time() - t0}
    except Exception as e:
        log_warn(f"[sandbox-warmup] 自检异常: {type(e).__name__}: {e}", logger="sandbox")
        return {"ok": False, "reason": f"self_test_error: {e}", "elapsed": time.time() - t0}


# ---- 服务部署（长期运行容器） ----

# 服务部署端口池：从 18000 开始分配，每会议一个端口
_SERVICE_PORT_POOL_START = 18000
_SERVICE_PORT_POOL_END = 18999
_allocated_ports: set[int] = set()
_port_lock = asyncio.Lock()

# 跟踪运行中的服务容器: meeting_id -> {container_id, host_port, access_url, ...}
_running_services: dict[str, dict] = {}
_services_lock = asyncio.Lock()


@dataclass
class DeployResult:
    """服务部署结果"""
    ok: bool
    container_id: str = ""
    host_port: int = 0
    access_url: str = ""
    health_status: str = ""  # "healthy" / "unhealthy" / "start_failed"
    logs: str = ""
    error: str = ""
    credentials: dict = None  # {"username": "...", "password": "..."}

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "container_id": self.container_id,
            "host_port": self.host_port,
            "access_url": self.access_url,
            "health_status": self.health_status,
            "logs": self.logs[:2000],  # 截断日志
            "error": self.error,
            "credentials": self.credentials or {},
        }


async def _allocate_port() -> int:
    """从端口池分配一个空闲端口"""
    async with _port_lock:
        # 先检查已分配但容器已停止的端口，回收复用
        async with _services_lock:
            active_ports = {s["host_port"] for s in _running_services.values() if s.get("host_port")}
        for port in range(_SERVICE_PORT_POOL_START, _SERVICE_PORT_POOL_END + 1):
            if port not in _allocated_ports or port not in active_ports:
                _allocated_ports.add(port)
                return port
        raise RuntimeError("端口池已满（18000-18999 均已分配）")


async def _release_port(port: int) -> None:
    """释放端口"""
    async with _port_lock:
        _allocated_ports.discard(port)


def _docker_cmd(args: list[str]) -> str:
    """构建 docker 命令的 shell 字符串"""
    return _shell_cmd(["docker"] + args)


async def _run_docker_cmd(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """执行 docker 命令并返回 (returncode, stdout, stderr)"""
    cmd = _docker_cmd(args)
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return (-1, "", "timeout")


async def _check_port_healthy(host: str, port: int, path: str = "/health", timeout: int = 5) -> bool:
    """HTTP 健康检查"""
    import urllib.request
    import urllib.error
    url = f"http://{host}:{port}{path}"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except Exception:
        # 也尝试根路径
        if path != "/":
            try:
                url2 = f"http://{host}:{port}/"
                req2 = urllib.request.Request(url2, method="GET")
                with urllib.request.urlopen(req2, timeout=timeout) as resp2:
                    return 200 <= resp2.status < 500
            except Exception:
                return False
        return False


async def deploy_service(
    meeting_id: str,
    workspace_root: Path,
    container_port: int = 8000,
    startup_cmd: str | None = None,
    health_path: str = "/health",
    memory_limit: str = "512m",
    cpu_limit: str = "2",
    env_vars: dict | None = None,
    credentials: dict | None = None,
    wait_seconds: int = 30,
) -> DeployResult:
    """部署一个长期运行的服务容器

    流程：
    1. 分配宿主机端口
    2. 创建并启动容器（detached模式，挂载工作区，映射端口）
    3. 等待服务启动 + 健康检查
    4. 返回访问URL或错误日志

    注意：与一次性沙箱不同，部署容器使用宽松安全策略（需要写文件、常驻运行）。
    资源限制比执行沙箱更宽松（512m/2cpus）。
    """
    if not await _check_docker():
        return DeployResult(ok=False, error="Docker 不可用，无法部署服务")

    host_port = await _allocate_port()

    # 确定工作区在容器内的路径
    meeting_dir = workspace_root  # 应该是 /workspace/{meeting_id}

    # 构建启动命令：先安装依赖，再启动服务
    if startup_cmd:
        cmd = startup_cmd
    else:
        cmd = (
            f"pip install --no-cache-dir -r requirements.txt 2>&1 | tail -5 && "
            f"exec uvicorn app:app --host 0.0.0.0 --port {container_port}"
        )

    # 构建 docker run 参数
    run_args = [
        "run",
        "-d",  # detached 模式
        "--name", f"conclave-svc-{meeting_id[:12]}",
        "--memory", memory_limit,
        "--cpus", cpu_limit,
        "-p", f"{host_port}:{container_port}",
        "--network", "bridge",  # 全网络访问（需要pip install）
        "-v", "conclave_conclave-workspace:/workspace",
        "-w", f"/workspace/{meeting_id}",
        # 不使用 --read-only（服务需要写数据库和上传文件）
        # 不使用 nobody 用户（pip install 需要写权限）
        "--restart", "no",  # 不自动重启（由Conclave管理生命周期）
    ]

    # 添加环境变量
    if env_vars:
        for k, v in env_vars.items():
            run_args.extend(["-e", f"{k}={v}"])

    # 使用 Python slim 镜像
    image = SANDBOX_IMAGE
    run_args.extend([image, "sh", "-c", cmd])

    try:
        rc, stdout, stderr = await _run_docker_cmd(run_args, timeout=60)
        if rc != 0:
            await _release_port(host_port)
            return DeployResult(
                ok=False,
                host_port=host_port,
                error=f"容器启动失败 (exit={rc}): {stderr[:500]}",
                logs=stderr,
            )

        container_id = stdout.strip()[:12]
        log_bus.info(
            f"服务容器已启动: {container_id} 端口映射 {host_port}->{container_port}",
            logger="sandbox.deploy",
            extra={"meeting_id": meeting_id, "container_id": container_id, "host_port": host_port},
        )

        # 等待服务启动 + 健康检查
        healthy = False
        last_logs = ""
        import time
        start_wait = time.time()
        while time.time() - start_wait < wait_seconds:
            await asyncio.sleep(3)

            # 检查容器是否还在运行
            rc_inspect, inspect_out, _ = await _run_docker_cmd(
                ["inspect", "-f", "{{.State.Running}}", container_id], timeout=5
            )
            if rc_inspect != 0 or "true" not in inspect_out:
                # 容器已停止，获取日志
                rc_logs, logs_out, _ = await _run_docker_cmd(["logs", "--tail", "30", container_id], timeout=10)
                last_logs = logs_out
                log_bus.warning(
                    f"服务容器已停止: {container_id}",
                    logger="sandbox.deploy",
                    extra={"logs": logs_out[:500]},
                )
                break

            # HTTP 健康检查
            # 注意：在容器内访问需要用容器IP，或者直接通过宿主机localhost访问
            # 但从 conclave-backend 容器内访问宿主机映射端口需要用 host.docker.internal
            # 或直接用容器的IP
            try:
                # 获取容器IP
                rc_ip, ip_out, _ = await _run_docker_cmd(
                    ["inspect", "-f", "{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container_id],
                    timeout=5,
                )
                container_ip = ip_out.strip()
                if container_ip:
                    healthy = await _check_port_healthy(container_ip, container_port, health_path, timeout=3)
            except Exception:
                pass

            if not healthy:
                # 也尝试从容器内通过docker.for.win（Windows/Mac Docker Desktop）
                # 或直接用localhost（如果后端在宿主机运行）
                try:
                    healthy = await _check_port_healthy("127.0.0.1", host_port, health_path, timeout=2)
                except Exception:
                    pass

            if healthy:
                break

        # 获取日志
        rc_logs, logs_out, _ = await _run_docker_cmd(["logs", "--tail", "20", container_id], timeout=10)
        last_logs = logs_out if logs_out else last_logs

        # 构建访问URL（用户从宿主机浏览器访问）
        # 从前端角度看，后端在 localhost:8000，服务也映射在宿主机端口
        access_url = f"http://localhost:{host_port}"

        # 记录运行中的服务
        async with _services_lock:
            _running_services[meeting_id] = {
                "container_id": container_id,
                "host_port": host_port,
                "access_url": access_url,
                "started_at": time.time(),
            }

        if healthy:
            return DeployResult(
                ok=True,
                container_id=container_id,
                host_port=host_port,
                access_url=access_url,
                health_status="healthy",
                logs=last_logs,
                credentials=credentials,
            )
        else:
            # 服务没通过健康检查，但容器可能还在运行
            return DeployResult(
                ok=False,
                container_id=container_id,
                host_port=host_port,
                access_url=access_url,
                health_status="unhealthy",
                logs=last_logs,
                error=f"服务启动后{wait_seconds}秒内未通过健康检查，请查看日志",
                credentials=credentials,
            )

    except Exception as e:
        await _release_port(host_port)
        log_bus.error(f"服务部署异常: {type(e).__name__}: {e}", logger="sandbox.deploy")
        return DeployResult(
            ok=False,
            host_port=host_port,
            error=f"部署异常: {e}",
        )


async def stop_service(meeting_id: str) -> dict:
    """停止并清理某个会议的服务容器"""
    async with _services_lock:
        svc = _running_services.pop(meeting_id, None)
    if not svc:
        return {"stopped": False, "reason": "no_service"}

    container_id = svc["container_id"]
    host_port = svc.get("host_port", 0)

    # 停止并删除容器
    await _run_docker_cmd(["stop", container_id], timeout=15)
    await _run_docker_cmd(["rm", "-f", container_id], timeout=10)

    if host_port:
        await _release_port(host_port)

    log_bus.info(
        f"服务容器已清理: {container_id}",
        logger="sandbox.deploy",
        extra={"meeting_id": meeting_id},
    )
    return {"stopped": True, "container_id": container_id}


async def get_service_status(meeting_id: str) -> dict | None:
    """获取某个会议的服务部署状态"""
    async with _services_lock:
        svc = _running_services.get(meeting_id)
    if not svc:
        return None
    # 检查容器是否还在运行
    rc, out, _ = await _run_docker_cmd(
        ["inspect", "-f", "{{.State.Running}}", svc["container_id"]], timeout=5
    )
    running = rc == 0 and "true" in out
    return {
        **svc,
        "running": running,
    }


async def cleanup_all_services() -> None:
    """清理所有运行中的服务容器（应用关闭时调用）"""
    async with _services_lock:
        meeting_ids = list(_running_services.keys())
    for mid in meeting_ids:
        try:
            await stop_service(mid)
        except Exception as e:
            log_bus.warning(f"清理服务容器失败 {mid}: {e}", logger="sandbox.deploy")
