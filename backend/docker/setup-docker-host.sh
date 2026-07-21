#!/bin/bash
# Conclave 远程 Docker 主机一键配置脚本
# 在目标 Linux 服务器上以 root 运行：
#   curl -sSL https://your-conclave-instance/setup-docker-host.sh | bash
# 或复制本脚本内容粘贴到服务器终端运行。
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

if ! grep -q "tcp://" "$DOCKER_DAEMON_JSON" 2>/dev/null; then
    echo "[2/5] 配置 Docker TCP 监听 (2375, 仅内网/带TLS时用)..."
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

# 3. 创建 conclave 用户
if ! id conclave &>/dev/null; then
    echo "[3/5] 创建 conclave 用户..."
    useradd -m -s /bin/bash -G docker conclave
    su - conclave -c 'ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519'
    echo "  请将以下公钥添加到 Conclave 运维面板:"
    echo "  ---"
    su - conclave -c 'cat ~/.ssh/id_ed25519.pub'
    echo "  ---"
else
    echo "[3/5] conclave 用户已存在"
fi

# 4. 配置防火墙
if command -v ufw &>/dev/null; then
    echo "[4/5] 配置 UFW 防火墙..."
    ufw allow 22/tcp comment "SSH"
    ufw --force reload
elif command -v firewall-cmd &>/dev/null; then
    echo "[4/5] 配置 firewalld..."
    firewall-cmd --permanent --add-port=22/tcp
    firewall-cmd --reload
else
    echo "[4/5] 未检测到 UFW/firewalld，请手动配置防火墙"
fi

# 5. 预拉取基础镜像
echo "[5/5] 预拉取基础镜像..."
docker pull python:3.12-slim 2>/dev/null &
docker pull node:20-slim 2>/dev/null &
docker pull nginx:1.27-alpine 2>/dev/null &
docker pull postgres:16-alpine 2>/dev/null &
wait

SERVER_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "=== 配置完成 ==="
echo "服务器 IP: $SERVER_IP"
echo "Docker 版本: $(docker --version)"
echo "运行容器数: $(docker ps -q | wc -l)"
echo ""
echo "推荐连接方式: SSH 密钥"
echo "  Docker Host: ssh://root@${SERVER_IP}:22"
echo "  SSH 用户: root"
echo "  SSH 端口: 22"
echo "  SSH 私钥: 使用 root 用户的 ~/.ssh/id_rsa 或新建密钥对"
echo ""
echo "安全建议:"
echo "  1. 公网环境使用 SSH 密钥而非 TCP 直连"
echo "  2. 将 conclave 用户加入 docker 组避免 root 操作"
echo "  3. SSH 密钥建议使用 ed25519 算法"
echo "  4. 修改 SSH 默认端口、禁用密码登录"
