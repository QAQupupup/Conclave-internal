# 运维面板 API：快照 + 历史 + 组件连通性
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("")
async def get_metrics() -> dict[str, Any]:
    """即时快照：系统资源 + Conclave 指标 + 吞吐量"""
    try:
        from app.observability.metrics_store import get_metrics_store

        store = get_metrics_store()
        base = store.snapshot()

        # 补充 LLM 成本数据
        cost_data: dict[str, Any] = {}
        try:
            from app.observability.cost_tracker import get_cost_tracker

            ct = get_cost_tracker()
            s = ct.summary()
            cost_data = {
                "total_tokens": s.get("total_tokens", 0),
                "total_llm_tokens": s.get("total_llm_tokens", 0),
                "total_cost_usd": s.get("total_cost_usd", 0.0),
                "total_calls": s.get("total_calls", 0),
                "llm_calls": s.get("llm_calls", 0),
                "tool_calls": s.get("tool_calls", 0),
                "error_count": s.get("error_count", 0),
                "by_node": s.get("by_node", {}),
                "by_tool": s.get("by_tool", {}),
            }
        except Exception:
            pass

        # 补充基础设施健康状态
        infra = await _health_checks()

        return {**base, "llm": cost_data, "infrastructure": infra}

    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.get("/history")
async def get_metrics_history(minutes: int = 60) -> dict[str, Any]:
    """时序数据：用于前端图表渲染

    Args:
        minutes: 返回最近 N 分钟的数据（默认 60）
    """
    try:
        from app.observability.metrics_store import get_metrics_store

        store = get_metrics_store()
        all_points = store.history()

        if not all_points:
            return {"resolution_seconds": 10, "points": []}

        # 按时间窗口过滤
        import time

        cutoff = time.time() - minutes * 60
        filtered = [p for p in all_points if p.timestamp >= cutoff]

        points = [
            {
                "ts": p.timestamp,
                "cpu": p.cpu_percent,
                "memory_mb": p.memory_mb,
                "memory_pct": p.memory_percent,
                "tokens": p.total_tokens,
                "cost_usd": p.total_cost_usd,
                "requests_total": p.api_requests_total,
                "requests_per_min": p.api_requests_per_minute,
                "latency_ms": p.avg_latency_ms,
                "meetings": p.active_meetings,
                "browser_ctx": p.browser_contexts,
            }
            for p in filtered
        ]

        return {"resolution_seconds": 10, "points": points}

    except Exception as e:
        return {"status": "error", "error": str(e), "resolution_seconds": 10, "points": []}


@router.get("/health")
async def get_health_detail() -> dict[str, Any]:
    """组件连通性详情（比 /health 更丰富的状态信息）"""
    return await _health_checks()


async def _health_checks() -> dict[str, Any]:
    """执行所有基础设施健康检查"""
    checks: dict[str, Any] = {}

    # 同步 PostgreSQL 兼容层检查
    try:
        import time as _time

        t0 = _time.monotonic()
        from app.db_legacy import _connect, _putconn

        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
            checks["postgresql"] = {
                "status": "ok",
                "latency_ms": round((_time.monotonic() - t0) * 1000, 1),
            }
        finally:
            _putconn(conn)
    except Exception as e:
        checks["postgresql"] = {"status": "error", "message": str(e)[:100]}

    # Qdrant
    try:
        import time as _time
        import httpx

        t0 = _time.monotonic()
        qdrant_url = os.environ.get(
            "CONCLAVE_QDRANT_URL",
            os.environ.get("QDRANT_URL", "http://qdrant:6333"),
        )
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{qdrant_url}/healthz")
            checks["qdrant"] = {
                "status": "ok" if resp.status_code == 200 else "error",
                "latency_ms": round((_time.monotonic() - t0) * 1000, 1),
                "code": resp.status_code,
            }
    except Exception as e:
        checks["qdrant"] = {"status": "error", "message": type(e).__name__}

    # Docker
    # [v2 修复] 原版用 `docker info` 子进程，在容器内无 docker CLI 时必失败
    # 旧版问题：容器内既无 docker binary 也无 /var/run/docker.sock，每次都返回 error
    #           但用户角度看 Docker 服务是正常运行的（其他容器都在）
    # 新版三档检测：
    #   1) 优先通过 DOCKER_HOST 远程 daemon API（生产推荐）
    #   2) 否则检测本地 socket 存在性（决定是"未配置"还是"错误"）
    #   3) 都没有 → 'unavailable'（表示后端未配置 docker 访问，不是错误）
    try:
        import asyncio as _aio
        import time as _time
        import httpx
        from pathlib import Path as _Path

        t0 = _time.monotonic()
        docker_disabled = os.environ.get("CONCLAVE_DOCKER_DISABLED", "").lower() in ("1", "true", "yes")
        docker_host = os.environ.get("CONCLAVE_DOCKER_HOST", "").strip()
        docker_socket = _Path("/var/run/docker.sock")

        if docker_disabled:
            checks["docker"] = {
                "status": "unavailable",
                "message": "Docker 监控已在环境变量中禁用",
                "latency_ms": 0.0,
            }
        elif docker_host:
            # 远程 daemon：HTTP 调用 /_ping
            try:
                async with httpx.AsyncClient(timeout=2) as client:
                    resp = await client.get(f"{docker_host.rstrip('/')}/_ping")
                    ok = resp.status_code == 200
                checks["docker"] = {
                    "status": "ok" if ok else "error",
                    "latency_ms": round((_time.monotonic() - t0) * 1000, 1),
                    "code": resp.status_code,
                }
            except Exception as e:
                checks["docker"] = {
                    "status": "unavailable",
                    "message": f"远程 Docker 守护进程不可达: {type(e).__name__}",
                    "latency_ms": round((_time.monotonic() - t0) * 1000, 1),
                }
        elif docker_socket.exists():
            # 本地 socket：尝试调用 CLI
            try:
                proc = await _aio.create_subprocess_exec(
                    "docker", "info",
                    stdout=_aio.subprocess.DEVNULL,
                    stderr=_aio.subprocess.DEVNULL,
                )
                await _aio.wait_for(proc.wait(), timeout=3)
                checks["docker"] = {
                    "status": "ok" if proc.returncode == 0 else "error",
                    "latency_ms": round((_time.monotonic() - t0) * 1000, 1),
                }
            except Exception as e:
                checks["docker"] = {
                    "status": "error",
                    "message": f"{type(e).__name__}",
                    "latency_ms": round((_time.monotonic() - t0) * 1000, 1),
                }
        else:
            # 容器内未挂载 socket + 未配置 DOCKER_HOST → 标记为 unavailable（非错误）
            # 这是常见部署场景：backend 与 docker 守护进程不在同一节点
            checks["docker"] = {
                "status": "unavailable",
                "message": "后端未配置 Docker 访问（缺少 /var/run/docker.sock 与 CONCLAVE_DOCKER_HOST）",
                "latency_ms": 0.0,
            }
    except Exception as e:
        checks["docker"] = {"status": "error", "message": type(e).__name__}

    # LLM 熔断器
    try:
        from app.agents.llm import get_circuit_breaker

        cb = get_circuit_breaker()
        checks["llm_circuit"] = {
            "status": cb.state,
            "failures": getattr(cb, "_failures", 0),
            "threshold": getattr(cb, "_threshold", 5),
        }
    except Exception:
        checks["llm_circuit"] = {"status": "unknown"}

    # 浏览器池
    try:
        from app.tools.browser_tool import get_browser_pool

        pool = get_browser_pool()
        checks["browser_pool"] = {
            "status": "ok",
            "active_contexts": pool.context_count,
        }
    except Exception:
        checks["browser_pool"] = {"status": "unknown"}

    # 沙箱
    try:
        from app.sandbox import get_status

        sandbox = await get_status()
        checks["sandbox"] = {
            "status": "ok" if sandbox.get("docker_available") else "unavailable",
            "mode": sandbox.get("mode", "unknown"),
            "image": sandbox.get("image", ""),
        }
    except Exception:
        checks["sandbox"] = {"status": "unknown"}

    # 整体状态
    # [v2 修复] 把 unavailable/idle/unknown 排除出"严重"判定
    # 原版：unavailable 也算"非 healthy" → 只要有组件未挂载就报 degraded
    # 现状：unavailable 表示"后端没配置这个组件的访问"或"组件在另一节点"，不是错误
    healthy = {"ok", "closed", "half_open"}
    benign = {"unavailable", "unknown", "idle"}  # 视为可接受
    # 计算"严重"组件：状态不是 healthy 也不是 benign
    severe = [k for k, c in checks.items() if isinstance(c, dict) and c.get("status") not in healthy and c.get("status") not in benign]
    all_ok = len(severe) == 0
    return {
        "status": "ok" if all_ok else "degraded",
        "components": checks,
        "degraded_components": severe,
    }