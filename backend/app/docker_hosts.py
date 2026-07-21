"""Docker 主机管理：连接检测、健康检查、调度策略、远程命令执行。

支持的连接方式：
  - local: 本地 unix socket（使用 docker CLI 默认配置）
  - tcp: 远程 TCP（无 TLS）
  - tcp_tls: 远程 TCP + TLS 证书
  - ssh_key: SSH 密钥认证
  - ssh_password: SSH 密码认证
  - docker_context: 使用已配置的 docker context
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sqlalchemy import select

logger = logging.getLogger(__name__)


# ─── 常量 ─────────────────────────────────────────────
CONNECTION_TYPES = [
    ("local", "本地 Socket", "使用本机 Docker daemon（/var/run/docker.sock）"),
    ("tcp", "远程 TCP (无TLS)", "内网环境，DOCKER_HOST=tcp://host:2375"),
    ("tcp_tls", "远程 TCP + TLS", "公网安全连接，需要 CA/Cert/Key"),
    ("ssh_key", "SSH 密钥", "通过 SSH 隧道连接，推荐远程方案"),
    ("ssh_password", "SSH 密码", "通过 SSH 密码连接（不推荐生产）"),
    ("docker_context", "Docker Context", "使用 docker context use 切换"),
]

# 7 套预设配置模板
PRESET_CONFIGS = {
    "local_unix": {
        "label": "本地 Unix Socket",
        "description": "本机 Docker Desktop / Linux 原生 Docker",
        "connection_type": "local",
        "docker_host": "",
        "ssh_user": "",
        "ssh_port": 22,
        "ssh_key_path": "",
        "tls_verify": True,
        "tags": ["local"],
        "region": "local",
    },
    "local_tcp": {
        "label": "本地 TCP (开发)",
        "description": "本机暴露 TCP 2375 端口（仅开发用）",
        "connection_type": "tcp",
        "docker_host": "tcp://127.0.0.1:2375",
        "ssh_user": "",
        "ssh_port": 22,
        "ssh_key_path": "",
        "tls_verify": False,
        "tags": ["local", "dev"],
        "region": "local",
    },
    "remote_tcp_tls": {
        "label": "远程 TCP + TLS (公网)",
        "description": "服务器开启 Docker TCP TLS（2376端口）",
        "connection_type": "tcp_tls",
        "docker_host": "tcp://YOUR_SERVER_IP:2376",
        "ssh_user": "",
        "ssh_port": 22,
        "ssh_key_path": "",
        "tls_verify": True,
        "tags": ["remote", "production"],
        "region": "remote",
    },
    "ssh_key_root": {
        "label": "SSH Root + 密钥 (推荐)",
        "description": "SSH root 用户 + 私钥文件，最常用远程方案",
        "connection_type": "ssh_key",
        "docker_host": "ssh://root@YOUR_SERVER_IP:22",
        "ssh_user": "root",
        "ssh_port": 22,
        "ssh_key_path": "~/.ssh/id_rsa",
        "tls_verify": True,
        "tags": ["remote", "recommended"],
        "region": "remote",
    },
    "ssh_key_ubuntu": {
        "label": "SSH Ubuntu 用户",
        "description": "云服务器默认 ubuntu 用户，需要 docker 组权限",
        "connection_type": "ssh_key",
        "docker_host": "ssh://ubuntu@YOUR_SERVER_IP:22",
        "ssh_user": "ubuntu",
        "ssh_port": 22,
        "ssh_key_path": "~/.ssh/id_rsa",
        "tls_verify": True,
        "tags": ["remote", "aws", "cloud"],
        "region": "cloud",
    },
    "ssh_password": {
        "label": "SSH 密码认证",
        "description": "用户名+密码连接（内网测试用，不推荐生产）",
        "connection_type": "ssh_password",
        "docker_host": "ssh://USER@YOUR_SERVER_IP:22",
        "ssh_user": "root",
        "ssh_port": 22,
        "ssh_key_path": "",
        "tls_verify": True,
        "tags": ["remote", "testing"],
        "region": "remote",
    },
    "docker_context": {
        "label": "Docker Context",
        "description": "使用本机已配置的 docker context（docker context use xxx）",
        "connection_type": "docker_context",
        "docker_host": "",
        "ssh_user": "",
        "ssh_port": 22,
        "ssh_key_path": "",
        "tls_verify": True,
        "tags": ["context", "multi-host"],
        "region": "managed",
    },
}


# ─── 调度策略 ─────────────────────────────────────────
class SchedulingStrategy(str, Enum):
    LEAST_LOADED = "least_loaded"  # 最少运行容器数
    TAG_MATCH = "tag_match"  # 标签匹配优先
    MANUAL = "manual"  # 手动指定
    ROUND_ROBIN = "round_robin"  # 轮询
    LOCAL_FIRST = "local_first"  # 本地优先，本地满了再远程


@dataclass
class HostHealthInfo:
    """主机健康信息"""

    ok: bool = False
    docker_version: str = ""
    running_containers: int = 0
    total_containers: int = 0
    cpu_count: int = 0
    memory_total_gb: float = 0.0
    error: str = ""
    latency_ms: int = 0


@dataclass
class DeployTarget:
    """部署目标选择结果"""

    host_id: int
    host_name: str
    connection_type: str
    docker_host_env: str  # DOCKER_HOST 环境变量值
    extra_env: dict[str, str] = field(default_factory=dict)
    reason: str = ""


# ─── Docker 命令执行 ──────────────────────────────────
def build_docker_env(host_config: dict[str, Any] | None = None) -> dict[str, str]:
    """根据主机配置构建 docker 命令所需的环境变量。"""
    env = os.environ.copy()

    if not host_config or host_config.get("connection_type") == "local":
        # 本地模式：清除可能存在的 DOCKER_HOST，使用默认 socket
        env.pop("DOCKER_HOST", None)
        env.pop("DOCKER_TLS_VERIFY", None)
        env.pop("DOCKER_CERT_PATH", None)
        return env

    ctype = host_config.get("connection_type", "local")
    docker_host_val = host_config.get("docker_host", "")

    if ctype == "tcp":
        env["DOCKER_HOST"] = docker_host_val
        env.pop("DOCKER_TLS_VERIFY", None)
        env.pop("DOCKER_CERT_PATH", None)

    elif ctype == "tcp_tls":
        env["DOCKER_HOST"] = docker_host_val
        if host_config.get("tls_verify", True):
            env["DOCKER_TLS_VERIFY"] = "1"
        cert_dir = host_config.get("_cert_dir", "")
        if cert_dir:
            env["DOCKER_CERT_PATH"] = cert_dir

    elif ctype in ("ssh_key", "ssh_password"):
        # SSH 连接：docker CLI 自动通过 DOCKER_HOST=ssh://... 连接
        env["DOCKER_HOST"] = docker_host_val
        # SSH 密钥路径
        key_path = host_config.get("ssh_key_path", "")
        if key_path and ctype == "ssh_key":
            env["DOCKER_SSH_IDENTITY"] = key_path
        # 不验证 host key（首次连接不阻塞）
        env.setdefault("DOCKER_SSH_FLAGS", "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null")

    elif ctype == "docker_context":
        context_name = host_config.get("context_name", "")
        if context_name:
            env["DOCKER_CONTEXT"] = context_name

    return env


async def run_docker_cmd(
    args: list[str],
    host_config: dict[str, Any] | None = None,
    timeout: int = 30,
    capture: bool = True,
) -> tuple[int, str, str]:
    """在指定主机上执行 docker 命令。

    返回 (returncode, stdout, stderr)。
    """
    env = build_docker_env(host_config)

    # 对于 SSH 密钥连接，如果有密钥内容写入临时文件
    tmp_key_path = None
    if host_config and host_config.get("connection_type") == "ssh_key":
        key_content = host_config.get("_ssh_key_content", "")
        if key_content:
            with tempfile.NamedTemporaryFile(mode="w", suffix="_id_rsa", delete=False) as f:
                f.write(key_content)
                tmp_key_path = f.name
            os.chmod(tmp_key_path, 0o600)
            env["DOCKER_SSH_IDENTITY"] = tmp_key_path

    cmd = ["docker", *args]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE if capture else None,
            stderr=asyncio.subprocess.PIPE if capture else None,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            stdout = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
            stderr = stderr_b.decode("utf-8", errors="replace") if stderr_b else ""
            return proc.returncode or 0, stdout, stderr
        except asyncio.TimeoutError:
            proc.kill()
            return -1, "", f"timeout after {timeout}s"
    except FileNotFoundError:
        return -1, "", "docker CLI not found"
    finally:
        if tmp_key_path:
            with contextlib.suppress(OSError):
                os.unlink(tmp_key_path)


async def check_host_health(host_config: dict[str, Any]) -> HostHealthInfo:
    """检查 Docker 主机健康状态。"""
    t0 = time.time()
    info = HostHealthInfo()

    # 1. docker version
    rc, stdout, stderr = await run_docker_cmd(
        ["version", "--format", "{{.Server.Version}}"],
        host_config=host_config,
        timeout=15,
    )
    if rc != 0:
        info.error = f"docker version failed: {stderr[:300]}"
        return info
    info.docker_version = stdout.strip()

    # 2. docker info (容器数量、资源)
    rc, stdout, stderr = await run_docker_cmd(
        ["info", "--format", "{{.ContainersRunning}}|{{.Containers}}|{{.NCPU}}|{{.MemTotal}}"],
        host_config=host_config,
        timeout=15,
    )
    if rc == 0 and "|" in stdout:
        parts = stdout.strip().split("|")
        try:
            info.running_containers = int(parts[0])
            info.total_containers = int(parts[1])
            info.cpu_count = int(parts[2])
            mem_bytes = int(parts[3])
            info.memory_total_gb = round(mem_bytes / (1024**3), 1)
        except (ValueError, IndexError):
            pass

    info.ok = True
    info.latency_ms = int((time.time() - t0) * 1000)
    return info


# ─── 调度器 ──────────────────────────────────────────
async def select_deploy_target(
    requirements: dict[str, Any] | None = None,
    preferred_host_id: int | None = None,
    strategy: str = "least_loaded",
) -> DeployTarget | None:
    """根据调度策略选择部署目标主机。

    requirements 可包含:
      - tags: list[str]       需要的标签
      - min_memory_gb: int    最小内存
      - min_cpu_cores: int    最小CPU
      - region: str           优先区域
    """
    from sqlalchemy import or_

    from app.db.engine import async_session_factory
    from app.db.models.docker_host import DockerHostModel
    from app.tenants import current_tenant_id

    requirements = requirements or {}
    tid = current_tenant_id()

    async with async_session_factory() as session:
        q = select(DockerHostModel).where(DockerHostModel.enabled == True)  # noqa: E712
        if tid is not None:
            q = q.where(or_(DockerHostModel.tenant_id == tid, DockerHostModel.tenant_id.is_(None)))
        result = await session.execute(q)
        hosts = list(result.scalars().all())

    if not hosts:
        # 无注册主机时返回 None，调用方应使用本地默认
        return None

    # 手动指定
    if preferred_host_id is not None:
        for h in hosts:
            if h.id == preferred_host_id:
                return _to_deploy_target(h, reason="手动指定")
        return None

    # 过滤健康主机
    healthy = [h for h in hosts if h.health_status == "healthy"]
    if not healthy:
        # 降级：使用全部启用主机
        healthy = hosts

    # 标签匹配过滤
    req_tags = set(requirements.get("tags", []))
    if req_tags:
        tagged = [h for h in healthy if req_tags.issubset(set(h.tags or []))]
        if tagged:
            healthy = tagged

    # 资源过滤
    min_mem = requirements.get("min_memory_gb", 0)
    min_cpu = requirements.get("min_cpu_cores", 0)
    if min_mem or min_cpu:
        capable = [
            h
            for h in healthy
            if (h.memory_gb >= min_mem or h.memory_gb == 0) and (h.cpu_cores >= min_cpu or h.cpu_cores == 0)
        ]
        if capable:
            healthy = capable

    if not healthy:
        return None

    # 本地优先
    if strategy == SchedulingStrategy.LOCAL_FIRST.value:
        local = [h for h in healthy if h.connection_type == "local" or "local" in (h.tags or [])]
        if local:
            healthy = local

    # 选择策略
    if strategy in (SchedulingStrategy.LEAST_LOADED.value, SchedulingStrategy.LOCAL_FIRST.value):
        chosen = min(healthy, key=lambda h: h.running_containers)
    elif strategy == SchedulingStrategy.ROUND_ROBIN.value:
        # 简单轮询：选 running_containers 最少的（近似）
        chosen = min(healthy, key=lambda h: (h.running_containers, h.id))
    elif strategy == SchedulingStrategy.TAG_MATCH.value:
        # 标签匹配度最高 + 负载最低
        def tag_score(h):
            h_tags = set(h.tags or [])
            match = len(req_tags & h_tags)
            return (-match, h.running_containers)

        chosen = min(healthy, key=tag_score)
    else:
        chosen = healthy[0]

    return _to_deploy_target(chosen, reason=f"策略: {strategy}")


def _to_deploy_target(host: Any, reason: str) -> DeployTarget:
    """将 ORM 对象转为 DeployTarget。"""
    ctype = host.connection_type
    docker_host_env = host.docker_host

    extra_env: dict[str, str] = {}
    if ctype == "local":
        docker_host_env = ""  # 本地默认
    elif ctype in ("ssh_key", "ssh_password"):
        # docker_host 已经是 ssh://user@host:port
        if host.ssh_key_path:
            extra_env["DOCKER_SSH_IDENTITY"] = host.ssh_key_path
    elif ctype == "tcp_tls":
        extra_env["DOCKER_TLS_VERIFY"] = "1" if host.tls_verify else "0"

    return DeployTarget(
        host_id=host.id,
        host_name=host.name,
        connection_type=ctype,
        docker_host_env=docker_host_env,
        extra_env=extra_env,
        reason=reason,
    )


# ─── 预设远程主机安装脚本 ─────────────────────────────
REMOTE_SETUP_SCRIPT = r"""#!/bin/bash
# Conclave 远程 Docker 主机一键配置脚本
# 在目标 Linux 服务器上以 root 运行：
#   curl -sSL https://raw.githubusercontent.com/.../setup-docker-host.sh | bash
# 或者复制以下脚本内容粘贴运行。

set -euo pipefail

echo "=== Conclave 远程 Docker 主机配置 ==="
echo ""

# 1. 安装 Docker（如果未安装）
if ! command -v docker &>/dev/null; then
    echo "[1/5] 安装 Docker..."
    curl -fsSL https://get.docker.com | bash
    systemctl enable --now docker
else
    echo "[1/5] Docker 已安装: $(docker --version)"
fi

# 2. 配置 Docker 监听 TCP（可选，用于 tcp:// 连接方式）
DOCKER_DAEMON_JSON="/etc/docker/daemon.json"
if [ ! -f "$DOCKER_DAEMON_JSON" ]; then
    echo '{}' > "$DOCKER_DAEMON_JSON"
fi

# 检查是否已配置 TCP
if ! grep -q "tcp://" "$DOCKER_DAEMON_JSON" 2>/dev/null; then
    echo "[2/5] 配置 Docker TCP 监听 (2375, 仅内网/带TLS时用)..."
    # 创建 systemd override
    mkdir -p /etc/systemd/system/docker.service.d
    cat > /etc/systemd/system/docker.service.d/override.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd -H fd:// -H tcp://0.0.0.0:2375 --containerd=/run/containerd/containerd.sock
EOF
    systemctl daemon-reload
    systemctl restart docker
    echo "  TCP 监听已启用: 0.0.0.0:2375"
else
    echo "[2/5] Docker TCP 已配置"
fi

# 3. 创建 conclave 用户（可选，建议非root操作）
if ! id conclave &>/dev/null; then
    echo "[3/5] 创建 conclave 用户..."
    useradd -m -s /bin/bash -G docker conclave
    # 生成 SSH 密钥对
    su - conclave -c 'ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519'
    echo "  请将公钥添加到 Conclave 运维面板:"
    echo "  ---"
    su - conclave -c 'cat ~/.ssh/id_ed25519.pub'
    echo "  ---"
else
    echo "[3/5] conclave 用户已存在"
fi

# 4. 配置防火墙（开放 Docker 端口）
if command -v ufw &>/dev/null; then
    echo "[4/5] 配置 UFW 防火墙..."
    ufw allow 22/tcp comment "SSH"
    # 仅在需要 TCP 直连时开放 2375
    # ufw allow from 你的Conclave服务器IP to any port 2375 comment "Docker API"
    ufw --force reload
elif command -v firewall-cmd &>/dev/null; then
    echo "[4/5] 配置 firewalld..."
    firewall-cmd --permanent --add-port=22/tcp
    firewall-cmd --reload
else
    echo "[4/5] 未检测到 UFW/firewalld，请手动配置防火墙"
fi

# 5. 拉取基础镜像（加速首次部署）
echo "[5/5] 预拉取基础镜像..."
docker pull python:3.12-slim 2>/dev/null &
docker pull node:20-slim 2>/dev/null &
docker pull nginx:1.27-alpine 2>/dev/null &
docker pull postgres:16-alpine 2>/dev/null &
wait

# 获取服务器信息
SERVER_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "=== 配置完成 ==="
echo "服务器 IP: $SERVER_IP"
echo "Docker 版本: $(docker --version)"
echo "运行容器数: $(docker ps -q | wc -l)"
echo ""
echo "在 Conclave 运维面板中添加主机时，请使用以下信息:"
echo "  连接方式: SSH 密钥"
echo "  Docker Host: ssh://conclave@${SERVER_IP}:22"
echo "  SSH 用户: conclave"
echo "  SSH 端口: 22"
echo "  SSH 密钥: 将上面的公钥添加到面板，或直接使用 root 账号"
echo ""
echo "如果使用 root SSH 密钥方式:"
echo "  Docker Host: ssh://root@${SERVER_IP}:22"
echo "  SSH 用户: root"
echo ""
echo "=== 安全建议 ==="
echo "1. 公网环境请使用 SSH 密钥而非 TCP 直连"
echo "2. 建议配置 TLS 证书后再开放 2376 端口"
echo "3. 将 conclave 用户加入 docker 组避免 root 操作"
echo "4. SSH 密钥建议使用 ed25519 算法"
"""


def get_remote_setup_script() -> str:
    """返回远程主机配置脚本内容。"""
    return REMOTE_SETUP_SCRIPT
