"""Docker 主机 ORM 模型。

支持多种连接方式：本地 unix socket、TCP、TCP+TLS、SSH 密钥、SSH 密码、Docker Context。
"""
from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import String, Text, Integer, Boolean, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DockerHostModel(Base):
    """Docker 主机注册表"""
    __tablename__ = "docker_hosts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # 连接配置
    connection_type: Mapped[str] = mapped_column(String(20), nullable=False, default="local")
    # local = 本地 unix socket（默认，无需额外配置）
    # tcp = 远程 TCP（无 TLS，内网使用）
    # tcp_tls = 远程 TCP + TLS（公网推荐）
    # ssh_key = SSH 密钥认证（推荐远程方案）
    # ssh_password = SSH 密码认证
    # docker_context = 使用本机已配置的 docker context
    docker_host: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # unix:///var/run/docker.sock / tcp://1.2.3.4:2375 / ssh://user@host:22
    ssh_user: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    ssh_port: Mapped[int] = mapped_column(Integer, nullable=False, default=22)
    ssh_key_path: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # SSH 密码加密存储（AES），此处留字段；实际通过 secret 字段存 JSON
    tls_cert_path: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    tls_key_path: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    tls_ca_path: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    tls_verify: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # 调度标签与资源
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # 示例: ["gpu", "high-mem", "china-net", "us-west", "dev"]
    region: Mapped[str] = mapped_column(String(50), nullable=False, default="local")
    cpu_cores: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    memory_gb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_containers: Mapped[int] = mapped_column(Integer, nullable=False, default=20)

    # 状态
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    health_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    # unknown / healthy / unhealthy / connecting
    last_health_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    docker_version: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    running_containers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_containers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # 部署记录：此主机上部署了哪些 meeting
    deployed_meetings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # ["mtg-xxx", "mtg-yyy"]

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class DockerHostSecretModel(Base):
    """敏感字段分离存储（SSH 密码、TLS key 内容等）"""
    __tablename__ = "docker_host_secrets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    host_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    ssh_password: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ssh_key_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tls_cert_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tls_key_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tls_ca_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
