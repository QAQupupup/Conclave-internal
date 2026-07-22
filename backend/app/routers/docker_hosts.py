"""Docker 主机管理 API。

提供 Docker 远程主机的 CRUD、健康检查、调度查询、预设配置、远程安装脚本。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.db.engine import async_session_factory
from app.db.models.docker_host import DockerHostModel, DockerHostSecretModel
from app.docker_hosts import (
    CONNECTION_TYPES,
    PRESET_CONFIGS,
    SchedulingStrategy,
    check_host_health,
    get_remote_setup_script,
    run_docker_cmd,
    select_deploy_target,
)
from app.tenants import current_tenant_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/docker-hosts", tags=["docker-hosts"])


def _tenant_filter():
    """返回租户过滤条件：当前租户的主机 + 系统主机(tenant_id IS NULL)"""
    tid = current_tenant_id()
    if tid is None:
        return DockerHostModel.tenant_id.is_(None)
    return or_(DockerHostModel.tenant_id == tid, DockerHostModel.tenant_id.is_(None))


def _tenant_filter_for_update():
    """返回租户更新过滤条件：只能修改自己租户的主机"""
    tid = current_tenant_id()
    if tid is None:
        return DockerHostModel.tenant_id.is_(None)
    return DockerHostModel.tenant_id == tid


async def _get_host_with_access(session, host_id: int, for_write: bool = False) -> DockerHostModel:
    """获取主机并校验租户访问权限。for_write=True 时仅允许访问自己租户的主机。"""
    from sqlalchemy import and_

    if for_write:
        cond = and_(DockerHostModel.id == host_id, _tenant_filter_for_update())
    else:
        cond = and_(DockerHostModel.id == host_id, _tenant_filter())
    result = await session.execute(select(DockerHostModel).where(cond))
    host: DockerHostModel | None = result.scalar_one_or_none()
    if not host:
        raise HTTPException(404, "主机不存在或无权访问")
    return host


# ─── Pydantic Schemas ────────────────────────────────
class DockerHostCreate(BaseModel):
    name: str = Field(..., max_length=100)
    description: str = ""
    connection_type: str = "local"
    docker_host: str = ""
    ssh_user: str = ""
    ssh_port: int = 22
    ssh_key_path: str = ""
    ssh_password: str = ""  # 写入 secret 表
    ssh_key_content: str = ""  # 直接粘贴私钥内容
    tls_cert_path: str = ""
    tls_key_path: str = ""
    tls_ca_path: str = ""
    tls_verify: bool = True
    tags: list[str] = []
    region: str = "local"
    cpu_cores: int = 0
    memory_gb: int = 0
    max_containers: int = 20
    enabled: bool = True
    is_default: bool = False


class DockerHostUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    connection_type: str | None = None
    docker_host: str | None = None
    ssh_user: str | None = None
    ssh_port: int | None = None
    ssh_key_path: str | None = None
    ssh_password: str | None = None
    ssh_key_content: str | None = None
    tls_cert_path: str | None = None
    tls_key_path: str | None = None
    tls_ca_path: str | None = None
    tls_verify: bool | None = None
    tags: list[str] | None = None
    region: str | None = None
    cpu_cores: int | None = None
    memory_gb: int | None = None
    max_containers: int | None = None
    enabled: bool | None = None
    is_default: bool | None = None


class DockerHostResponse(BaseModel):
    id: int
    name: str
    description: str
    connection_type: str
    docker_host: str
    ssh_user: str
    ssh_port: int
    ssh_key_path: str
    tls_cert_path: str
    tls_verify: bool
    tags: list[str]
    region: str
    cpu_cores: int
    memory_gb: int
    max_containers: int
    enabled: bool
    is_default: bool
    health_status: str
    last_health_check: str | None
    docker_version: str
    running_containers: int
    total_containers: int
    last_error: str
    deployed_meetings: list[str]
    created_at: str
    updated_at: str


def _model_to_response(m: DockerHostModel) -> dict[str, Any]:
    return {
        "id": m.id,
        "name": m.name,
        "description": m.description,
        "connection_type": m.connection_type,
        "docker_host": m.docker_host,
        "ssh_user": m.ssh_user,
        "ssh_port": m.ssh_port,
        "ssh_key_path": m.ssh_key_path,
        "tls_cert_path": m.tls_cert_path,
        "tls_verify": m.tls_verify,
        "tags": m.tags or [],
        "region": m.region,
        "cpu_cores": m.cpu_cores,
        "memory_gb": m.memory_gb,
        "max_containers": m.max_containers,
        "enabled": m.enabled,
        "is_default": m.is_default,
        "health_status": m.health_status,
        "last_health_check": m.last_health_check.isoformat() if m.last_health_check else None,
        "docker_version": m.docker_version,
        "running_containers": m.running_containers,
        "total_containers": m.total_containers,
        "last_error": m.last_error,
        "deployed_meetings": m.deployed_meetings or [],
        "created_at": m.created_at.isoformat() if m.created_at else "",
        "updated_at": m.updated_at.isoformat() if m.updated_at else "",
    }


def _model_to_config_dict(m: DockerHostModel, secret: DockerHostSecretModel | None = None) -> dict[str, Any]:
    """转换为 docker_hosts 模块使用的配置 dict。"""
    cfg: dict[str, Any] = {
        "connection_type": m.connection_type,
        "docker_host": m.docker_host,
        "ssh_user": m.ssh_user,
        "ssh_port": m.ssh_port,
        "ssh_key_path": m.ssh_key_path,
        "tls_verify": m.tls_verify,
    }
    if secret and secret.ssh_key_content:
        cfg["_ssh_key_content"] = secret.ssh_key_content
    return cfg


# ─── CRUD Endpoints ──────────────────────────────────
@router.get("")
async def list_hosts() -> dict[str, Any]:
    """列出当前租户可见的 Docker 主机（含系统主机）。"""
    async with async_session_factory() as session:
        result = await session.execute(select(DockerHostModel).where(_tenant_filter()).order_by(DockerHostModel.id))
        hosts = list(result.scalars().all())
    return {
        "hosts": [_model_to_response(h) for h in hosts],
        "total": len(hosts),
    }


@router.post("")
async def create_host(body: DockerHostCreate) -> dict[str, Any]:
    """创建 Docker 主机（归属于当前租户）。"""
    tid = current_tenant_id()
    async with async_session_factory() as session:
        # 检查名称唯一（在当前租户范围内）
        existing = await session.execute(
            select(DockerHostModel).where(
                DockerHostModel.name == body.name,
                _tenant_filter_for_update() if tid is not None else DockerHostModel.tenant_id.is_(None),
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(400, f"主机名 '{body.name}' 已存在")

        # 如果设为默认，清除同租户其他默认
        if body.is_default:
            all_hosts = (
                (
                    await session.execute(
                        select(DockerHostModel).where(
                            DockerHostModel.is_default == True,  # noqa: E712
                            _tenant_filter_for_update() if tid is not None else DockerHostModel.tenant_id.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for h in all_hosts:
                h.is_default = False

        host = DockerHostModel(
            tenant_id=tid,
            name=body.name,
            description=body.description,
            connection_type=body.connection_type,
            docker_host=body.docker_host,
            ssh_user=body.ssh_user,
            ssh_port=body.ssh_port,
            ssh_key_path=body.ssh_key_path,
            tls_cert_path=body.tls_cert_path,
            tls_key_path=body.tls_key_path,
            tls_ca_path=body.tls_ca_path,
            tls_verify=body.tls_verify,
            tags=body.tags,
            region=body.region,
            cpu_cores=body.cpu_cores,
            memory_gb=body.memory_gb,
            max_containers=body.max_containers,
            enabled=body.enabled,
            is_default=body.is_default,
        )
        session.add(host)
        await session.flush()

        # 存储敏感信息
        if body.ssh_password or body.ssh_key_content:
            secret = DockerHostSecretModel(
                host_id=host.id,
                ssh_password=body.ssh_password,
                ssh_key_content=body.ssh_key_content,
            )
            session.add(secret)

        await session.commit()
        await session.refresh(host)

    return _model_to_response(host)


@router.get("/{host_id}")
async def get_host(host_id: int) -> dict[str, Any]:
    """获取单个主机详情。"""
    async with async_session_factory() as session:
        host = await _get_host_with_access(session, host_id)
    return _model_to_response(host)


@router.put("/{host_id}")
async def update_host(host_id: int, body: DockerHostUpdate) -> dict[str, Any]:
    """更新 Docker 主机。"""
    async with async_session_factory() as session:
        host = await _get_host_with_access(session, host_id, for_write=True)

        update_data = body.model_dump(exclude_unset=True)
        secret_fields = {"ssh_password", "ssh_key_content"}
        secret_updates = {k: v for k, v in update_data.items() if k in secret_fields}
        base_updates = {k: v for k, v in update_data.items() if k not in secret_fields}

        for k, v in base_updates.items():
            setattr(host, k, v)

        tid = current_tenant_id()
        if base_updates.get("is_default"):
            others = (
                (
                    await session.execute(
                        select(DockerHostModel).where(
                            DockerHostModel.id != host_id,
                            DockerHostModel.is_default == True,  # noqa: E712
                            _tenant_filter_for_update() if tid is not None else DockerHostModel.tenant_id.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for h in others:
                h.is_default = False

        if secret_updates:
            secret = (
                await session.execute(select(DockerHostSecretModel).where(DockerHostSecretModel.host_id == host_id))
            ).scalar_one_or_none()
            if not secret:
                secret = DockerHostSecretModel(host_id=host_id)
                session.add(secret)
            for k, v in secret_updates.items():
                setattr(secret, k, v)

        host.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(host)

    return _model_to_response(host)


@router.delete("/{host_id}")
async def delete_host(host_id: int) -> dict[str, Any]:
    """删除 Docker 主机。"""
    async with async_session_factory() as session:
        host = await _get_host_with_access(session, host_id, for_write=True)
        # 删除关联 secret
        secret = (
            await session.execute(select(DockerHostSecretModel).where(DockerHostSecretModel.host_id == host_id))
        ).scalar_one_or_none()
        if secret:
            await session.delete(secret)
        await session.delete(host)
        await session.commit()
    return {"ok": True, "deleted": host_id}


# ─── 健康检查 ────────────────────────────────────────
@router.post("/{host_id}/health-check")
async def health_check_host(host_id: int) -> dict[str, Any]:
    """对指定主机执行健康检查。"""
    async with async_session_factory() as session:
        host = await _get_host_with_access(session, host_id)
        secret = (
            await session.execute(select(DockerHostSecretModel).where(DockerHostSecretModel.host_id == host_id))
        ).scalar_one_or_none()

        config = _model_to_config_dict(host, secret)

    # 异步执行健康检查（避免阻塞）
    health = await check_host_health(config)

    # 更新状态
    async with async_session_factory() as session:
        host_refreshed: DockerHostModel | None = await session.get(DockerHostModel, host_id)
        if host_refreshed:
            host_refreshed.health_status = "healthy" if health.ok else "unhealthy"
            host_refreshed.last_health_check = datetime.now(timezone.utc)
            host_refreshed.docker_version = health.docker_version
            host_refreshed.running_containers = health.running_containers
            host_refreshed.total_containers = health.total_containers
            host_refreshed.last_error = health.error
            if health.cpu_count and not host_refreshed.cpu_cores:
                host_refreshed.cpu_cores = health.cpu_count
            if health.memory_total_gb and not host_refreshed.memory_gb:
                host_refreshed.memory_gb = int(health.memory_total_gb)
            await session.commit()
            await session.refresh(host_refreshed)
            return {
                **_model_to_response(host_refreshed),
                "health_detail": {
                    "ok": health.ok,
                    "latency_ms": health.latency_ms,
                    "cpu_count": health.cpu_count,
                    "memory_gb": health.memory_total_gb,
                    "error": health.error,
                },
            }

    return {"ok": False, "error": "更新失败"}


@router.post("/health-check-all")
async def health_check_all() -> dict[str, Any]:
    """对当前租户可见的所有启用主机执行批量健康检查。"""
    async with async_session_factory() as session:
        result = await session.execute(
            select(DockerHostModel).where(
                DockerHostModel.enabled == True,  # noqa: E712
                _tenant_filter(),
            )
        )
        hosts = list(result.scalars().all())
        secrets = {}
        for h in hosts:
            s = (
                await session.execute(select(DockerHostSecretModel).where(DockerHostSecretModel.host_id == h.id))
            ).scalar_one_or_none()
            secrets[h.id] = s

    results = []
    for host in hosts:
        config = _model_to_config_dict(host, secrets.get(host.id))
        health = await check_host_health(config)
        results.append(
            {
                "host_id": host.id,
                "name": host.name,
                "ok": health.ok,
                "version": health.docker_version,
                "running": health.running_containers,
                "latency_ms": health.latency_ms,
                "error": health.error,
            }
        )

    # 批量更新状态
    async with async_session_factory() as session:
        for r in results:
            host_update: DockerHostModel | None = await session.get(DockerHostModel, r["host_id"])
            if host_update:
                host_update.health_status = "healthy" if r["ok"] else "unhealthy"
                host_update.last_health_check = datetime.now(timezone.utc)
                host_update.docker_version = str(r["version"])
                host_update.running_containers = r["running"]  # type: ignore[assignment]
                host_update.last_error = str(r["error"])
        await session.commit()

    return {"checked": len(results), "results": results}


# ─── 调度查询 ────────────────────────────────────────
@router.post("/select-target")
async def select_target(
    requirements: dict[str, Any] | None = None,
    preferred_host_id: int | None = None,
    strategy: str = "least_loaded",
) -> dict[str, Any]:
    """根据策略选择部署目标主机。"""
    target = await select_deploy_target(
        requirements=requirements,
        preferred_host_id=preferred_host_id,
        strategy=strategy,
    )
    if not target:
        return {
            "selected": False,
            "fallback": "local",
            "reason": "无可用主机，使用本地 Docker",
        }
    return {
        "selected": True,
        "host_id": target.host_id,
        "host_name": target.host_name,
        "connection_type": target.connection_type,
        "docker_host": target.docker_host_env,
        "extra_env": target.extra_env,
        "reason": target.reason,
    }


@router.get("/scheduling/strategies")
async def list_strategies() -> dict[str, Any]:
    """列出可用调度策略。"""
    return {"strategies": [{"key": s.value, "label": s.name} for s in SchedulingStrategy]}


# ─── 预设配置 ────────────────────────────────────────
@router.get("/presets")
async def list_presets() -> dict[str, Any]:
    """获取7套预设连接配置模板。"""
    return {
        "presets": [{"key": k, "config": v, "fields": _get_preset_fields(k)} for k, v in PRESET_CONFIGS.items()],
        "connection_types": [{"value": t[0], "label": t[1], "description": t[2]} for t in CONNECTION_TYPES],
        "required_fields": _get_required_fields_map(),
    }


def _get_preset_fields(key: str) -> list[dict[str, Any]]:
    """返回每个预设需要用户填写的字段列表。"""
    fields_map = {
        "local_unix": [],
        "local_tcp": [
            {"key": "docker_host", "label": "Docker Host", "placeholder": "tcp://127.0.0.1:2375", "required": True},
        ],
        "remote_tcp_tls": [
            {
                "key": "docker_host",
                "label": "Docker Host",
                "placeholder": "tcp://your-server-ip:2376",
                "required": True,
            },
            {"key": "tls_ca_content", "label": "CA 证书", "type": "textarea", "required": True},
            {"key": "tls_cert_content", "label": "客户端证书", "type": "textarea", "required": True},
            {"key": "tls_key_content", "label": "客户端私钥", "type": "textarea", "required": True},
        ],
        "ssh_key_root": [
            {
                "key": "docker_host",
                "label": "Docker Host (SSH地址)",
                "placeholder": "ssh://root@your-server-ip:22",
                "required": True,
            },
            {"key": "ssh_user", "label": "SSH 用户", "default": "root", "required": True},
            {
                "key": "ssh_key_content",
                "label": "SSH 私钥内容",
                "type": "textarea",
                "placeholder": "-----BEGIN OPENSSH PRIVATE KEY-----\n...",
                "required": True,
            },
        ],
        "ssh_key_ubuntu": [
            {
                "key": "docker_host",
                "label": "Docker Host (SSH地址)",
                "placeholder": "ssh://ubuntu@your-server-ip:22",
                "required": True,
            },
            {"key": "ssh_user", "label": "SSH 用户", "default": "ubuntu", "required": True},
            {
                "key": "ssh_key_content",
                "label": "SSH 私钥内容",
                "type": "textarea",
                "placeholder": "-----BEGIN OPENSSH PRIVATE KEY-----\n...",
                "required": True,
            },
        ],
        "ssh_password": [
            {
                "key": "docker_host",
                "label": "Docker Host (SSH地址)",
                "placeholder": "ssh://user@your-server-ip:22",
                "required": True,
            },
            {"key": "ssh_user", "label": "SSH 用户", "required": True},
            {"key": "ssh_password", "label": "SSH 密码", "type": "password", "required": True},
        ],
        "docker_context": [
            {"key": "context_name", "label": "Context 名称", "placeholder": "remote-server", "required": True},
        ],
    }
    return fields_map.get(key, [])


def _get_required_fields_map() -> dict[str, list[str]]:
    """每种连接类型需要的必填字段。"""
    return {
        "local": [],
        "tcp": ["docker_host"],
        "tcp_tls": ["docker_host"],
        "ssh_key": ["docker_host", "ssh_user", "ssh_key_content"],
        "ssh_password": ["docker_host", "ssh_user", "ssh_password"],
        "docker_context": ["docker_host"],
    }


# ─── 远程安装脚本 ────────────────────────────────────
@router.get("/setup-script")
async def get_setup_script() -> dict[str, Any]:
    """获取远程主机一键配置脚本。"""
    return {
        "script": get_remote_setup_script(),
        "instructions": [
            "1. 在目标 Linux 服务器上以 root 身份登录",
            "2. 复制脚本内容粘贴到终端执行，或使用 curl 命令",
            "3. 脚本会自动安装 Docker、配置 TCP 监听、创建 conclave 用户",
            "4. 执行完成后，将显示的 SSH 连接信息填入上方添加主机表单",
            "5. 推荐使用 SSH 密钥方式连接（安全）",
        ],
        "quick_install": (
            "curl -fsSL https://get.docker.com | bash && systemctl enable --now docker && usermod -aG docker $USER"
        ),
    }


# ─── 主机上的容器列表 ────────────────────────────────
@router.get("/{host_id}/containers")
async def list_containers(host_id: int) -> dict[str, Any]:
    """列出指定主机上运行的容器（包括 Conclave 部署的服务）。"""
    async with async_session_factory() as session:
        host = await _get_host_with_access(session, host_id)
        secret = (
            await session.execute(select(DockerHostSecretModel).where(DockerHostSecretModel.host_id == host_id))
        ).scalar_one_or_none()
        config = _model_to_config_dict(host, secret)

    rc, stdout, stderr = await run_docker_cmd(
        ["ps", "-a", "--format", "{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}"],
        host_config=config,
        timeout=15,
    )
    if rc != 0:
        return {"ok": False, "error": stderr, "containers": []}

    containers = []
    for line in stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|")
        if len(parts) >= 5:
            containers.append(
                {
                    "id": parts[0][:12],
                    "name": parts[1],
                    "image": parts[2],
                    "status": parts[3],
                    "ports": parts[4],
                }
            )
    return {"ok": True, "containers": containers, "host": host.name}
