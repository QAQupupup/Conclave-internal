# 代码摄入：Git 链接（含 submodule）+ zip 上传，落 workspace/{meeting_id}/ 会议目录
# Phase A（ADR-016）：只做"导入 + 文件树浏览"，图解析/图检索在 Phase B/C。
#
# 安全设计：
#   - Git 在 backend 侧以受控子进程执行（非 LLM shell），协议仅 http/https，参数由 exec(list) 传递无 shell 注入
#   - 认证 token 只注入 URL、不落盘、不记日志，错误输出脱敏
#   - 目标目录名安全化 + resolve().relative_to() 防路径穿越
#   - clone 后大小上限 + clone 超时（GIT_TERMINAL_PROMPT=0 防挂起等凭据）
#   - zip 解压逐条目校验 zip-slip（路径越界拒绝）
from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from app.config import settings
from app.observability.log_bus import log_bus
from app.rag.code_index import index_repo
from app.rag.graph_expand import structure_query
from app.schemas.code import CodeRetrieveRequest, StructureQueryRequest

logger = logging.getLogger("routers.code")

router = APIRouter(prefix="/meetings", tags=["code"])

# 会议工作区根目录（Docker 内 /workspace，本地 ~/.conclave/workspace）
WORKSPACE_ROOT = Path(settings.workspace_root).resolve()

# ---- 安全限制（环境变量可调） ----
# zip 上传大小上限（默认 200MB）
MAX_ZIP_SIZE = int(os.environ.get("CONCLAVE_CODE_INGEST_MAX_ZIP", str(200 * 1024 * 1024)))
# clone 后仓库大小上限（默认 500MB），超限整体删除
MAX_REPO_SIZE = int(os.environ.get("CONCLAVE_CODE_INGEST_MAX_REPO", str(500 * 1024 * 1024)))
# git clone 超时（默认 300s）
GIT_CLONE_TIMEOUT = int(os.environ.get("CONCLAVE_CODE_INGEST_GIT_TIMEOUT", "300"))

# 仅允许 http/https；SSH（git@host:path）Phase A 不支持（需 deploy key，放后续）
_ALLOWED_PROTOCOLS = ("https://", "http://")

# 目录名安全化：仅保留字母数字/中文/下划线/连字符/点，其余替换为下划线
_SAFE_DIR_RE = re.compile(r"[^\w\u4e00-\u9fff\-.]", re.UNICODE)


# ---- 辅助函数（纯逻辑，便于单元测试） ----


def _parse_repo_name(git_url: str) -> str:
    """从 Git URL 提取仓库名（去掉协议、认证前缀、查询片段、.git 后缀）。

    用 urlsplit 分离 scheme/netloc/path：认证前缀（user:token@）落在 netloc、
    查询/片段落在 query/fragment，取 path 末段即仓库名。退化 URL（如 ``https://``）
    无 path 时回退 "repo"，不产生越界或歧义目录名。
    """
    url = git_url.strip()
    parts = urlsplit(url)
    segments = [s for s in parts.path.split("/") if s]
    repo = segments[-1] if segments else ""
    if repo.endswith(".git"):
        repo = repo[:-4]
    return _sanitize_dir(repo) or "repo"


def _sanitize_dir(name: str) -> str:
    """目录名安全化：去除危险字符与 . / .. ，空返回空串。"""
    cleaned = _SAFE_DIR_RE.sub("_", name).strip("._")
    if cleaned in ("", ".", ".."):
        return ""
    return cleaned


def _inject_token(git_url: str, token: str | None) -> str:
    """将 HTTPS token 注入 URL 认证段（http/https 协议）。

    已含认证信息则不重复注入；token 做 URL 编码避免特殊字符破坏 URL。
    """
    if not token:
        return git_url
    token = quote(token, safe="")
    parts = urlsplit(git_url)
    if parts.username is not None:  # 已含 user[:pass]
        return git_url
    netloc = f"oauth2:{token}@{parts.netloc}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _redact(text: str, token: str | None) -> str:
    """错误输出脱敏：替换 token 与 oauth2:<token> 形式，避免泄露。"""
    if not token:
        return text
    text = text.replace(token, "***")
    text = text.replace(f"oauth2:{token}", "oauth2:***")
    return text


def _dir_size(path: Path) -> int:
    """递归统计目录内文件总字节数（用于 clone 后大小上限校验）。"""
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                continue
    return total


def _safe_extract_zip(zf: zipfile.ZipFile, dest: Path) -> int:
    """解压 zip 到 dest，逐条目校验路径越界（zip-slip）。返回解压文件数。"""
    dest = dest.resolve()
    count = 0
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        try:
            target.relative_to(dest)
        except ValueError:
            raise ValueError(f"压缩包包含越界路径，已拒绝: {member.filename}") from None
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        count += 1
    return count


def _resolve_dest(meeting_dir: Path, target_name: str) -> Path:
    """解析目标目录并防越界：必须落在会议目录内。空名抛错。"""
    if not target_name:
        raise ValueError("目标目录名无效")
    dest = (meeting_dir / target_name).resolve()
    try:
        dest.relative_to(meeting_dir.resolve())
    except ValueError:
        raise ValueError(f"目标目录越界: {target_name}") from None
    return dest


async def _run_git(meeting_dir: Path, args: list[str], timeout: int) -> tuple[int, str, str]:
    """在 backend 侧执行受控 git 命令（参数列表无 shell 注入，禁交互式凭据提示）。"""
    # GIT_TERMINAL_PROMPT=0：私有仓库/host key 校验缺失时快速失败，而非挂起等输入
    # GIT_LFS_SKIP_SMUDGE=1：跳过 LFS 大文件下载，Phase A 只管源码文本
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(meeting_dir),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"git clone 超时（{timeout}s）") from None
    return proc.returncode or 0, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")


async def _ensure_meeting_owned(meeting_id: str) -> None:
    """校验会议存在且属于当前租户（系统租户跳过）。"""
    from app.tenants.context import is_system_tenant

    if is_system_tenant():
        return
    from app.dao.meeting_dao import get_meeting

    meeting = await get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="会议不存在或不属于当前租户")


# ---- 摄入实现 ----


async def _ingest_git(
    meeting_dir: Path,
    meeting_id: str,
    git_url: str,
    branch: str | None,
    target_dir: str | None,
    token: str | None,
) -> dict[str, Any]:
    if not git_url.lower().startswith(_ALLOWED_PROTOCOLS):
        raise HTTPException(status_code=400, detail="仅支持 http/https Git URL，SSH 暂不支持")

    repo_name = _parse_repo_name(git_url)
    target_name = _sanitize_dir(target_dir) if target_dir else repo_name
    try:
        dest = _resolve_dest(meeting_dir, target_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if dest.exists():
        raise HTTPException(status_code=409, detail=f"目标目录已存在: {target_name}，请先删除或换目录")

    clone_url = _inject_token(git_url, token) if token else git_url

    args = ["clone", "--recurse-submodules", "--depth", "1", "--quiet"]
    if branch:
        args += ["--branch", branch]
    args += [clone_url, target_name]

    log_bus.info(
        "[code.ingest] git clone 开始",
        logger="routers.code",
        extra={
            "meeting_id": meeting_id,
            "repo": repo_name,
            "target": target_name,
            "has_token": bool(token),
            "branch": branch,
        },
    )

    try:
        rc, _stdout, stderr = await _run_git(meeting_dir, args, GIT_CLONE_TIMEOUT)
    except TimeoutError as e:
        # 超时后清理半成品目录
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(status_code=408, detail=str(e)) from e
    except FileNotFoundError:
        raise HTTPException(
            status_code=503, detail="git 未安装：请确认后端镜像已包含 git（详见 backend/Dockerfile）"
        ) from None

    if rc != 0:
        # 失败清理，脱敏后返回错误详情
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(status_code=502, detail=f"git clone 失败: {_redact(stderr, token)[:300]}")

    # 大小上限校验（递归 stat 属磁盘 I/O，放入线程池避免阻塞事件循环）
    size = await asyncio.to_thread(_dir_size, dest)
    if size > MAX_REPO_SIZE:
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(
            status_code=413,
            detail=f"仓库过大：{size // 1024 // 1024}MB，上限 {MAX_REPO_SIZE // 1024 // 1024}MB",
        )

    log_bus.info(
        "[code.ingest] git clone 完成",
        logger="routers.code",
        extra={"meeting_id": meeting_id, "target": target_name, "size_bytes": size},
    )

    return {
        "source_type": "git",
        "target_name": target_name,
        "size_bytes": size,
        "file_count": await asyncio.to_thread(_count_files, dest),
    }


async def _ingest_zip(
    meeting_dir: Path,
    meeting_id: str,
    file: UploadFile,
    target_dir: str | None,
) -> dict[str, Any]:
    raw = await file.read()
    if len(raw) > MAX_ZIP_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"压缩包过大：{len(raw) // 1024 // 1024}MB，上限 {MAX_ZIP_SIZE // 1024 // 1024}MB",
        )

    filename = file.filename or "code.zip"
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    target_name = _sanitize_dir(target_dir) if target_dir else _sanitize_dir(stem)
    try:
        dest = _resolve_dest(meeting_dir, target_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if dest.exists():
        raise HTTPException(status_code=409, detail=f"目标目录已存在: {target_name}")

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            # 解压写文件逐条目做 zip-slip 校验 + 落盘（磁盘 I/O），放入线程池避免阻塞事件循环
            count = await asyncio.to_thread(_safe_extract_zip, zf, dest)
    except zipfile.BadZipFile as e:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(status_code=400, detail="不是有效的 zip 文件") from e
    except ValueError as e:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(e)) from e

    size = await asyncio.to_thread(_dir_size, dest)
    if size > MAX_REPO_SIZE:
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(
            status_code=413,
            detail=f"解压后过大：{size // 1024 // 1024}MB，上限 {MAX_REPO_SIZE // 1024 // 1024}MB",
        )

    log_bus.info(
        "[code.ingest] zip 解压完成",
        logger="routers.code",
        extra={"meeting_id": meeting_id, "target": target_name, "files": count, "size_bytes": size},
    )

    return {"source_type": "zip", "target_name": target_name, "size_bytes": size, "file_count": count}


def _count_files(path: Path) -> int:
    """统计源码文件数（排除 .git 目录，避免 objects/pack 撑大计数）。"""
    return sum(1 for p in path.rglob("*") if p.is_file() and ".git" not in p.parts)


# ---- MeetingState 登记（[P1 修复] 打通"代码上传 → 会议感知"）----


def _register_code_in_state(state: Any, repo_info: dict[str, Any]) -> None:
    """把摄入的代码仓库登记进 MeetingState（纯逻辑，便于单元测试）。

    - state.code_repos 是权威清单：按 path 去重（重新摄入同名目录时替换旧记录）
    - state.doc_summaries 同步一条摘要：让 clarify 阶段"上传资料摘要"可见；
      先移除同名旧摘要再追加，避免重复摄入后摘要堆积
    """
    path = str(repo_info.get("path") or repo_info.get("name") or "")
    state.code_repos = [r for r in state.code_repos if r.get("path") != path]
    state.code_repos.append(repo_info)

    name = str(repo_info.get("name") or path)
    marker = f"代码库 {name}"
    state.doc_summaries = [s for s in state.doc_summaries if not s.startswith(marker)]
    state.doc_summaries.append(
        f"{marker}（{repo_info.get('file_count', 0)} 个文件，目录 {path}，来源 {repo_info.get('source_type', 'unknown')}）"
    )


async def _persist_state_lite(state: Any) -> None:
    """立即持久化会议状态（单 session 原子，与 Runner._persist 同源逻辑）。

    摄入多发生在会议启动前，若只改内存不落库，重启后登记会丢失、
    且重新摄入会撞 409（目录已存在），故摄入成功后立即落库。
    """
    from app.dao.meeting_aux_dao import save_meeting_aux
    from app.dao.meeting_dao import save_meeting
    from app.db.engine import async_session_factory

    aux = state.extract_aux()
    try:
        async with async_session_factory() as session:
            try:
                await save_meeting(
                    meeting_id=state.meeting_id,
                    topic=state.topic,
                    status=state.status.value,
                    stage=state.stage.value,
                    created_at=state.created_at,
                    payload=state.snapshot(),
                    session=session,
                )
                await save_meeting_aux(state.meeting_id, aux, session=session)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    finally:
        state.inject_aux(aux)


async def _register_code_to_state(meeting_id: str, repo_info: dict[str, Any]) -> bool:
    """把代码仓库登记进会议运行态并立即持久化。返回是否登记成功。

    - 优先取内存态；未命中且 DB 有记录时从 PostgreSQL 恢复（进程重启场景）
    - 登记/持久化失败不阻断摄入结果（文件已落盘，仍可浏览），仅告警
    """
    from app.orchestrator.runner import get_state, load_or_create

    try:
        state = get_state(meeting_id)
        if state is None:
            from app.dao.meeting_dao import get_meeting

            record = await get_meeting(meeting_id)
            if record is not None:
                state = await load_or_create(meeting_id, record.get("topic") or "")
        if state is None:
            logger.info("会议运行态不存在，跳过代码登记: meeting_id=%s", meeting_id)
            return False
        _register_code_in_state(state, repo_info)
        await _persist_state_lite(state)
        return True
    except Exception as e:
        logger.warning(
            "代码登记到会议状态失败（不影响摄入结果）: meeting_id=%s, %s: %s",
            meeting_id,
            type(e).__name__,
            e,
        )
        return False


# ---- 语义索引（ADR-018 Phase B） ----


def _resolve_tenant_id() -> int:
    """解析语义索引隔离键所需租户 ID。

    请求上下文无租户（开发模式未认证/系统租户）时用 0 作系统命名空间：
    真实租户 ID 从 1 起，不会与 0 冲突（D3 租户前缀隔离不受影响）。
    """
    from app.tenants.context import get_tenant_id

    tenant_id = get_tenant_id()
    return tenant_id if tenant_id is not None else 0


async def _build_semantic_index(repo_path: Path, meeting_id: str) -> dict[str, Any]:
    """构建仓库级语义索引（LightRAG）。失败不阻断摄入（降级哲学）。

    配额超限（QuotaExceededError）例外上抛：由全局异常处理器转 429，
    属显式预算语义，不应被吞成"索引失败可重试"。
    """
    from app.core.exceptions import QuotaExceededError
    from app.rag.semantic_ingest import ingest_repo_semantic

    try:
        return await ingest_repo_semantic(
            repo_path,
            meeting_id=meeting_id,
            tenant_id=_resolve_tenant_id(),
        )
    except QuotaExceededError:
        raise
    except Exception as e:
        logger.warning(
            "语义索引构建失败（不影响导入，可稍后重建）: meeting_id=%s, %s: %s",
            meeting_id,
            type(e).__name__,
            e,
        )
        return {"enabled": False, "reason": f"{type(e).__name__}: {e}", "docs_ingested": 0}


def _degraded_status(reason: str) -> dict[str, Any]:
    """进度查询的降级响应（语义层不可用/查询失败统一语义，前端据此提示可重试）。"""
    return {"enabled": False, "reason": reason, "status_counts": {}, "documents": []}


async def _semantic_index_status(meeting_id: str, track_id: str | None) -> dict[str, Any]:
    """查询语义索引 DocStatus 进度（与摄入同隔离键：会议级 workspace）。

    降级哲学与摄入一致：语义层不可用或查询失败返回 enabled=False（非 500），
    进度轮询不被存储故障打断；查询用毕立即关闭索引，不长期占用存储句柄。
    """
    from app.rag.lightrag_adapter import get_semantic_index

    index = get_semantic_index(_resolve_tenant_id(), meeting_id=meeting_id)
    if index is None:
        return _degraded_status("semantic_layer_unavailable")
    try:
        await index.initialize()
        try:
            progress = await index.get_progress(track_id)
        finally:
            await index.close()
    except Exception as e:
        logger.warning(
            "语义索引进度查询失败（降级返回）: meeting_id=%s, %s: %s",
            meeting_id,
            type(e).__name__,
            e,
        )
        return _degraded_status(f"{type(e).__name__}: {e}")
    return {"enabled": True, "workspace": index.workspace, **progress}


# ---- 端点 ----


@router.post("/{meeting_id}/code/ingest")
async def ingest_code(
    meeting_id: str,
    git_url: str | None = Form(default=None),
    branch: str | None = Form(default=None),
    target_dir: str | None = Form(default=None),
    token: str | None = Form(default=None),
    semantic_index: bool = Form(default=False),
    file: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    """导入代码库到会议工作区。

    二选一：`git_url`（http/https，递归 submodule）或 `file`（zip）。
    产物落在 `workspace/{meeting_id}/{target_dir|repo_name}/`，
    随后可通过 fs.list / fs.read / shell.exec 浏览。

    `semantic_index=true` 时额外构建 LightRAG 语义索引（ADR-018 Phase B）：
    分批摄入受配额约束，进度经 `GET .../code/index/status` 查询。
    """
    await _ensure_meeting_owned(meeting_id)

    if bool(git_url) == bool(file):
        raise HTTPException(status_code=400, detail="必须且只能提供 git_url 或 file（zip）之一")

    meeting_dir = WORKSPACE_ROOT / meeting_id
    meeting_dir.mkdir(parents=True, exist_ok=True)

    if git_url:
        result = await _ingest_git(meeting_dir, meeting_id, git_url.strip(), branch, target_dir, token)
    else:
        assert file is not None
        result = await _ingest_zip(meeting_dir, meeting_id, file, target_dir)

    target_name = result["target_name"]

    # 摄入后自动索引：构图 + 切块 + 注册图索引 + 向量入库（ADR-016 Phase B/C 接线）。
    # 索引失败不阻断导入（graceful 降级），代码仍可浏览；后续可重新触发索引。
    index_stats: dict[str, Any] | None = None
    try:
        index_stats = await index_repo(meeting_dir / target_name, meeting_id)
    except Exception as e:
        logger.warning(
            "代码索引失败（不影响导入，可稍后重新索引）: meeting_id=%s, %s: %s",
            meeting_id,
            type(e).__name__,
            e,
        )

    # [P1 修复] 登记 MeetingState：让会议流程感知"已导入代码"。
    # 代码锚点（conclave_core.anchor.get_code_anchor）会随各阶段 prompt 注入，
    # LLM 不再需要用户口述才知道代码在哪。登记失败不阻断摄入结果。
    registered = await _register_code_to_state(
        meeting_id,
        {
            "name": target_name,
            "path": target_name,
            "source_type": result["source_type"],
            "file_count": result["file_count"],
            "size_bytes": result["size_bytes"],
            "indexed": index_stats is not None,
        },
    )

    # 语义索引（ADR-018 Phase B）：semantic_index 开关控制，默认关闭；
    # 失败降级不阻断导入，配额超限例外上抛（见 _build_semantic_index）
    semantic_result: dict[str, Any] | None = None
    if semantic_index:
        semantic_result = await _build_semantic_index(meeting_dir / target_name, meeting_id)

    response: dict[str, Any] = {
        "meeting_id": meeting_id,
        "source_type": result["source_type"],
        # 会议相对路径：供 Agent 的 fs.list/fs.read（meeting_id 自动注入）使用
        "path": target_name,
        "root_dir": target_name,
        # 工作区相对路径：供前端 workspace 文件树使用
        "workspace_path": f"{meeting_id}/{target_name}".replace("\\", "/"),
        "size_bytes": result["size_bytes"],
        "file_count": result["file_count"],
        # 是否已登记到会议状态（False 表示仅落盘可浏览，prompt 暂不感知）
        "registered": registered,
    }
    if index_stats is not None:
        response["index"] = index_stats
    if semantic_result is not None:
        response["semantic_index"] = semantic_result
    return response


@router.post("/{meeting_id}/code/retrieve")
async def code_retrieve(
    meeting_id: str,
    body: CodeRetrieveRequest,
) -> dict[str, Any]:
    """代码检索（ADR-016 Phase C）：向量入口 + N 跳图扩展交 reranker。

    返回 ``results``（chunk 字典视图，图扩展命中项携带 ``graph_hit`` 元数据）。
    会议无代码索引时优雅降级为空结果；无图索引时退化为纯向量检索。
    """
    await _ensure_meeting_owned(meeting_id)
    # 延迟导入：retriever 顶部 import 了 hyde/query_rewriter（LLM 相关），
    # 仅在真正检索时加载，避免路由模块注册时拖慢启动（与 manager.py 一致）。
    from app.rag.retriever import retrieve_code

    results = await retrieve_code(meeting_id, body.query, top_k=body.top_k, max_hops=body.max_hops)
    return {"meeting_id": meeting_id, "count": len(results), "results": results}


@router.post("/{meeting_id}/code/structure")
async def code_structure(
    meeting_id: str,
    body: StructureQueryRequest,
) -> dict[str, Any]:
    """代码结构查询（ADR-016 Phase C.2）：给定符号/文件节点，返回「谁调用它」与「它依赖谁」。

    图索引未注册 / 节点不存在时返回空 callers/dependencies（调用方据此降级）。
    """
    await _ensure_meeting_owned(meeting_id)
    return structure_query(meeting_id, body.node_id, max_hops=body.max_hops)


@router.get("/{meeting_id}/code/index/status")
async def code_index_status(
    meeting_id: str,
    track_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """语义索引进度查询（ADR-018 Phase B）：DocStatus 状态计数 + 按批次明细。

    - 不传 `track_id`：仅返回 workspace 级各状态文档数（``status_counts``），
      避免大仓库全量枚举拖慢查询；
    - 传 `track_id`（摄入返回的批次凭据）：额外返回该批次逐文档状态（``documents``）。
    语义层不可用时返回 ``enabled=false``（降级语义，前端据此隐藏进度区）。
    """
    await _ensure_meeting_owned(meeting_id)
    return await _semantic_index_status(meeting_id, track_id)
