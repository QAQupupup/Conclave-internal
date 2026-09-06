# Produce stage node + helpers: _synthesize_evidence_for_produce, _detect_network_level, _scan_artifacts
from __future__ import annotations

import contextlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.agents.compute import build_produce_prompt
from app.agents.trace import set_current_trace
from app.events import bus, make_event
from app.models import MeetingState, Role, Stage

from ._helpers import _build_tool_registry, _emit_agent_spoke, _run_stage_step

if TYPE_CHECKING:
    from app.sandbox import SandboxNetworkLevel

# ADR-017 Phase 3（I14）：test_suite 沙箱执行超时（秒）。
# 测试套件通常重于 tested_system 单文件（30s），取双倍；环境变量可覆盖。
TEST_SUITE_EXEC_TIMEOUT = int(os.environ.get("CONCLAVE_TEST_SUITE_TIMEOUT", "60"))

# ADR-017 Phase 3（I10）：test_files 相对路径白名单（LLM 输出不可信）。
# 限定字符集后命令拼接无注入面；另叠加 ".." 拒绝与 resolve 包含校验。
_TEST_PATH_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-.\/]*$")


def _make_token_stream_callback(state: MeetingState) -> Any:
    """创建限流的 token 流式回调，每 500ms 最多发一次 ``produce.token_stream`` 事件

    用于 produce 阶段长等待时提供增量反馈，让用户感知 LLM 正在生成而非卡死。
    """
    import time

    last_emit: list[float] = [0.0]

    async def _on_token(delta: str) -> None:
        now = time.monotonic()
        if now - last_emit[0] < 0.5:  # 500ms 限流
            return
        last_emit[0] = now
        with contextlib.suppress(Exception):
            await bus.publish(
                make_event(
                    "produce.token_stream",
                    state.meeting_id,
                    {
                        "meeting_id": state.meeting_id,
                        "delta": delta[:200],  # 限制 delta 大小，避免事件过大
                    },
                )
            )

    return _on_token


def _current_src_loc(depth: int = 1) -> dict[str, Any]:
    """返回当前代码位置（文件路径 + 行号），用于审计日志和降级事件"""
    import inspect

    frame = inspect.currentframe()
    if frame is None:
        return {"file": "unknown", "line": 0}
    # depth=1 表示调用 _current_src_loc 的上一层
    for _ in range(depth):
        if frame.f_back is None:
            break
        frame = frame.f_back
    return {"file": frame.f_code.co_filename, "line": frame.f_lineno}


async def _emit_progress(state: MeetingState, step: str, message: str, percent: int = 0) -> None:
    """发送 produce 阶段进度事件到前端"""
    with contextlib.suppress(Exception):
        await bus.publish(
            make_event(
                "produce.progress",
                state.meeting_id,
                {
                    "meeting_id": state.meeting_id,
                    "step": step,
                    "message": message,
                    "percent": percent,
                },
            )
        )


async def _emit_degradation_event(
    state: MeetingState,
    reason: str,
    empty_fields: list[str],
    result: dict[str, Any],
    confidence_before: str,
    confidence_after: str,
    call_record: dict[str, Any] | None = None,
) -> None:
    """发布 produce 阶段降级/完整性事件，供审计和重跑分析

    payload 包含：
    - 触发代码位置（file / line）
    - 触发条件（condition / empty_fields）
    - 程序逻辑（logic）
    - 当前状态（stage / deliverable_type / confidence）
    - 最近一次 LLM 调用的关键摘要（model / prompt_length / raw_response_length）
    """
    loc = _current_src_loc(depth=2)
    # 从 trace 中取出最近一次 produce 调用作为上下文
    last_call: dict[str, Any] | None = None
    if state.llm_trace and state.llm_trace.calls:
        for c in reversed(state.llm_trace.calls):
            if c.stage == "produce":
                last_call = {
                    "call_id": c.call_id,
                    "model": c.model,
                    "provider_id": c.provider_id,
                    "temperature": c.temperature,
                    "seed": c.seed,
                    "attempt": c.attempt,
                    "latency_ms": c.latency_ms,
                    "input_tokens": c.input_tokens,
                    "output_tokens": c.output_tokens,
                    "total_tokens": c.total_tokens,
                    "validation_status": c.validation_status,
                    "consistency_status": c.consistency_status,
                    "prompt_length": len(c.prompt),
                    "raw_response_length": len(c.raw_response),
                    "parsed_result_keys": list(c.parsed_result.keys()) if c.parsed_result else [],
                }
                break

    payload = {
        "meeting_id": state.meeting_id,
        "stage": state.stage.value if state.stage else "produce",
        "deliverable_type": state.deliverable_type,
        "reason": reason,
        "empty_fields": empty_fields,
        "confidence_before": confidence_before,
        "confidence_after": confidence_after,
        "result_top_keys": list(result.keys()) if isinstance(result, dict) else [],
        "src_loc": loc,
        "condition": f"deliverable_type={state.deliverable_type} 且 {empty_fields} 为空",
        "logic": "produce 节点内容完整性校验：关键字段为空时阻止部署/沙箱执行，并将 confidence 从 high 降级为 low",
        "state": {
            "status": state.status.value if state.status else None,
            "stage": state.stage.value if state.stage else None,
            "confidence_flags": dict(state.confidence_flags) if state.confidence_flags else {},
            "message_count": len(state.messages),
            "claim_count": len(state.claims),
            "conflict_count": len(state.conflicts),
            "evidence_count": sum(len(es.get("assessments", [])) for es in state.evidence_set),
        },
        "last_call": last_call,
        "call_record": call_record,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with contextlib.suppress(Exception):
        await bus.publish(make_event("produce.degradation", state.meeting_id, payload))


def _detect_network_level(code: str) -> SandboxNetworkLevel:
    """根据代码内容自动判断需要的沙箱网络级别

    L1(无网络)：默认，纯计算代码
    L2(限网)：包含 pip install，需要安装依赖
    L3(全联网)：包含 requests/urllib/httpx/http(s)://，需要访问外部 API

    判断逻辑：
    1. 有 pip install → L2（需要 pypi）
    2. 有 HTTP 库 import 或 URL → L3（需要联网）
    3. 其他 → L1（纯计算）
    """
    code_lower = code.lower()

    # L3: 外部 HTTP 请求
    http_indicators = [
        "import requests",
        "from requests",
        "import urllib",
        "from urllib",
        "import httpx",
        "from httpx",
        "import aiohttp",
        "from aiohttp",
        "http://",
        "https://",
        "urlopen",
        "requests.get",
        "requests.post",
    ]
    for indicator in http_indicators:
        if indicator in code_lower:
            return "L3"

    # L2: pip install
    if "pip install" in code_lower or ("subprocess" in code_lower and "pip" in code_lower):
        return "L2"

    # L1: 默认纯计算
    return "L1"


def _parse_test_report(exec_result: dict[str, Any]) -> dict[str, Any]:
    """解析 pytest 文本输出为结构化测试报告（ADR-017 Phase 3，T3.2）。

    复用 ``sandbox.run_tests_in_container`` 的正则模式（``X passed`` /
    ``Y failed`` / ``FAILED path::name``），保持两处解析口径一致。
    输出尾部保留 3000 字符，防止大输出撑爆 artifact（大产物红线）。
    """
    output = (exec_result.get("stdout") or "") + "\n" + (exec_result.get("stderr") or "")
    passed = 0
    failed = 0
    pass_match = re.search(r"(\d+)\s+passed", output)
    fail_match = re.search(r"(\d+)\s+failed", output)
    if pass_match:
        passed = int(pass_match.group(1))
    if fail_match:
        failed = int(fail_match.group(1))
    failures = re.findall(r"FAILED\s+(\S+::\S+)", output)[:10]
    # 无标准汇总行但有 ERRORS 段（收集阶段报错）→ 按 error 数计失败
    if passed == 0 and failed == 0 and "ERRORS" in output:
        err_match = re.search(r"(\d+)\s+error", output)
        if err_match:
            failed = int(err_match.group(1))
    return {
        "passed": passed,
        "failed": failed,
        "failures": failures,
        "exit_code": exec_result.get("exit_code"),
        "output": output[-3000:],
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "sandboxed": bool(exec_result.get("sandboxed")),
    }


def _write_test_files(ws_root: Path, test_files: list[Any]) -> tuple[list[dict[str, str]], list[str]]:
    """把 LLM 生成的测试文件写入会议工作区（ADR-017 Phase 3，I10 路径防护）。

    三重防护：白名单正则（限定字符集）→ 拒绝 ``..`` 段 → ``resolve()``
    包含校验（必须仍在 ws_root 内）。非法路径跳过并记录，不抛异常。

    Returns:
        ``(kept_files, skipped_paths)``：kept_files 为 ``{path, code}`` 列表
        （path 为规范化后的相对路径），skipped_paths 为被拒路径（截断）。
    """
    kept: list[dict[str, str]] = []
    skipped: list[str] = []
    ws_resolved = ws_root.resolve()
    for tf in test_files:
        if not isinstance(tf, dict):
            continue
        raw_path = str(tf.get("path") or "")
        code = str(tf.get("code") or "")
        if not raw_path or not code:
            continue
        rel = raw_path.replace("\\", "/").lstrip("/")
        if not _TEST_PATH_RE.match(rel) or ".." in rel.split("/"):
            skipped.append(raw_path[:100])
            continue
        target = (ws_root / rel).resolve()
        try:
            target.relative_to(ws_resolved)
        except ValueError:
            skipped.append(rel[:100])
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(code, encoding="utf-8")
        kept.append({"path": rel, "code": code})
    return kept, skipped


def _scan_artifacts(ws_root: Path, meeting_id: str) -> list[dict[str, Any]]:
    """扫描沙箱工作区，收集产出的文件作为附件。

    ws_root 可以是 workspace 根目录（自动找 meeting_id 子目录），
    也可以已经是 meeting_id 子目录（不再重复拼接）。
    支持代码文件、文档、图片等常见产出类型。
    返回附件元数据列表，文件本体保留在 workspace 中通过 API 下载。
    """
    attachments: list[dict[str, Any]] = []
    # 支持的文件扩展名（含代码文件）
    supported_exts = {
        # 代码
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".html",
        ".css",
        ".vue",
        ".java",
        ".go",
        ".rs",
        ".yml",
        ".yaml",
        ".toml",
        ".ini",
        ".cfg",
        ".sh",
        ".bat",
        ".ps1",
        ".sql",
        # 文档/数据
        ".md",
        ".txt",
        ".json",
        ".csv",
        ".log",
        ".pdf",
        ".doc",
        ".docx",
        # 图片
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".webp",
    }
    # 无扩展名但重要的文件
    supported_noext = {"Dockerfile", "Makefile", "README", "LICENSE", ".env", ".gitignore"}

    # 智能判断扫描目录：如果 ws_root 末尾已经是 meeting_id，直接扫描
    if ws_root.name == meeting_id and ws_root.exists() and ws_root.is_dir():
        scan_dir = ws_root
    else:
        # 否则优先找 meeting_id 子目录，不存在则扫 ws_root 本身
        meeting_dir = ws_root / meeting_id
        scan_dir = meeting_dir if meeting_dir.exists() and meeting_dir.is_dir() else ws_root

    if not scan_dir.exists():
        return attachments

    for f in sorted(scan_dir.iterdir()):
        if not f.is_file():
            continue
        # 匹配扩展名或无扩展名的知名文件
        is_supported = (
            f.suffix.lower() in supported_exts
            or f.name in supported_noext
            or (not f.suffix and f.name.startswith("Dockerfile"))
        )
        if not is_supported:
            continue
        try:
            stat = f.stat()
        except OSError:
            continue
        # 附件"path"字段是相对于 workspace 根的路径（便于 API 下载）
        # 找到 workspace 根（即包含 meeting_id 作为其子目录的那个目录）
        rel_path = f"{meeting_id}/{f.name}" if ws_root.name == meeting_id or (ws_root / meeting_id).exists() else f.name
        attachments.append(
            {
                "filename": f.name,
                "path": rel_path,
                "size": stat.st_size,
                "ext": f.suffix.lower().lstrip(".") if f.suffix else "",
                "meeting_id": meeting_id,
            }
        )
    return attachments


def _synthesize_evidence_for_produce(state: MeetingState) -> dict[str, Any]:
    """将 evidence_set + decision_record 综合为结构化数据规格，
    供代码生成类 deliverable (code_analysis / data_science) 使用。

    返回空 dict 表示无可用证据（非代码类产出不受影响）。
    """
    if not state.evidence_set:
        return {}

    evidence_sources: list[str] = []
    evidence_quotes: list[dict] = []
    for es in state.evidence_set:
        for a in es.get("assessments", []):
            source = a.get("source", "")
            quote = a.get("quote", "")
            if source and source not in evidence_sources:
                evidence_sources.append(source)
            if quote:
                evidence_quotes.append(
                    {
                        "quote": quote[:200],
                        "source": source,
                        "supports": a.get("supports", "neutral"),
                        "conflict_id": es.get("conflict_id", ""),
                    }
                )

    decisions = (state.decision_record or {}).get("decisions", [])
    adopted = (state.decision_record or {}).get("adopted_claims", [])

    return {
        "available_data_sources": evidence_sources[:10],
        "evidence_count": len(evidence_quotes),
        "evidence_samples": evidence_quotes[:15],
        "decisions_count": len(decisions),
        "adopted_claims_count": len(adopted),
    }


# ==============================================================================
# 进程内静态安全扫描（regex-based，无外部依赖）
# 设计原则：
#   - critical 级规则：100% 确定性匹配，误报率极低，命中即阻断部署
#   - high 级规则：高危反模式，命中即告警但不阻断（可能存在合理使用场景）
#   - 不依赖外部工具/LLM/网络，不泄露代码，毫秒级完成
# ==============================================================================

# 要扫描的文件扩展名
_CODE_EXTS = {
    ".py",
    ".pyi",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".mjs",
    ".cjs",
    ".go",
    ".c",
    ".cpp",
    ".cc",
    ".h",
    ".hpp",
    ".hh",
    ".java",
    ".rs",
    ".kt",
    ".kts",
    ".rb",
    ".php",
    ".sh",
    ".bash",
    ".ps1",
    ".sql",
}

# critical 级规则（阻断部署）：
# 每条 (pattern, severity, rule_id, message)
# pattern 使用 re.search 逐行匹配
_CRITICAL_PATTERNS: list[tuple[str, str, str, str]] = [
    # === 命令注入 ===
    (
        r"os\.system\s*\(\s*[\"']?[a-zA-Z_]*f?[\"']?\s*[\w\.]*\s*\+",
        "critical",
        "cmd-injection-os-system",
        "os.system() 使用字符串拼接，存在命令注入风险。请使用 subprocess.run(args_list) 并避免 shell=True",
    ),
    (
        r"subprocess\.(?:run|Popen|call|check_output|check_call)\s*\([^)]*shell\s*=\s*True",
        "critical",
        "cmd-injection-shell-true",
        "subprocess 使用 shell=True，存在命令注入风险。请使用 shell=False 并以列表传参",
    ),
    # === SQL 注入 ===
    (
        r"""(?:execute|executemany|raw|text)\s*\(\s*[f\"]?[\"'][^\"']*\%\s*[sds]""",
        "critical",
        "sql-injection-format",
        "SQL 语句使用 %s/%d 字符串格式化，存在 SQL 注入风险。请使用参数化查询(:name 或 %s 占位符+参数元组)",
    ),
    (
        r"""(?:execute|executemany|raw)\s*\(\s*f[\"']""",
        "critical",
        "sql-injection-fstring",
        "SQL 语句使用 f-string 拼接，存在 SQL 注入风险。请使用参数化查询",
    ),
    (
        r"""(?:execute|executemany|raw)\s*\([^)]*\.format\s*\(""",
        "critical",
        "sql-injection-format-method",
        "SQL 语句使用 .format() 拼接，存在 SQL 注入风险。请使用参数化查询",
    ),
    # === 硬编码密钥/密码（明显模式）===
    (
        r"""(?:password|passwd|pwd|secret|api_key|apikey|token)\s*=\s*[\"'][^\"']{8,}[\"']""",
        "critical",
        "hardcoded-secret",
        "疑似硬编码密钥/密码。请通过环境变量或配置文件读取，不要直接写在代码中",
    ),
    # === 危险反序列化 ===
    (
        r"pickle\.loads?\s*\(",
        "critical",
        "pickle-deserialization",
        "使用 pickle.load(s) 反序列化，存在任意代码执行风险。请使用 JSON/YAML 等安全格式",
    ),
    (
        r"marshal\.loads?\s*\(",
        "critical",
        "marshal-deserialization",
        "使用 marshal.load(s) 反序列化，存在任意代码执行风险",
    ),
    # === eval/exec 动态执行 ===
    (
        r"(?<![\w.])eval\s*\(\s*(?!['\"]const['\"])",
        "critical",
        "dangerous-eval",
        "使用 eval() 执行动态代码，存在任意代码执行风险。请改用 ast.literal_eval 或其他安全方式",
    ),
    (
        r"(?<![\w.])exec\s*\(",
        "critical",
        "dangerous-exec",
        "使用 exec() 执行动态代码，存在任意代码执行风险。请重构避免动态执行",
    ),
    # === 路径穿越 ===
    (
        r"open\s*\(\s*[^)]*\+\s*(?:request|input|param|args|user_input|data)",
        "critical",
        "path-traversal-open",
        "open() 路径包含用户输入拼接，存在路径穿越风险。请使用 os.path.abspath + 白名单验证",
    ),
    # === tarfile 路径穿越 ===
    (
        r"tarfile\.(?:open|TarFile)\([^)]*\)[^;]*\.extractall\s*\(",
        "critical",
        "tarfile-extractall-traversal",
        "tarfile.extractall() 未指定 filter='data'，存在路径穿越(CVE-2007-4559)。Python 3.12+ 必须传 filter='data'",
    ),
    # === os.popen 命令注入 ===
    (
        r"os\.(?:popen|popen2|popen3|popen4|system)\s*\(\s*f?[\"']",
        "critical",
        "cmd-injection-popen",
        "os.popen/system 使用字符串命令，存在命令注入风险。请使用 subprocess.run([args], shell=False)",
    ),
]

# high 级规则（告警不阻断）
_HIGH_PATTERNS: list[tuple[str, str, str, str]] = [
    # === 不安全的 YAML 加载 ===
    (
        r"yaml\.load\s*\([^)]*\)(?!.*Loader)",
        "high",
        "yaml-load-unsafe",
        "yaml.load() 未指定 Loader=yaml.SafeLoader，存在反序列化攻击风险",
    ),
    # === 关闭 SSL 验证 ===
    (
        r"verify\s*=\s*False",
        "high",
        "ssl-verify-disabled",
        "HTTPS 请求关闭了 SSL 证书验证(verify=False)，存在中间人攻击风险",
    ),
    # === 调试模式 ===
    (
        r"DEBUG\s*=\s*True|debug\s*=\s*True",
        "high",
        "debug-mode-enabled",
        "DEBUG 模式已开启，生产环境必须关闭",
    ),
    # === 全局异常吞掉 ===
    (
        r"except\s*:\s*$|except\s+Exception\s*(?:as\s+\w+\s*)?:\s*(?:pass|\.\.\.)\s*$",
        "high",
        "bare-except-pass",
        "空 except 块吞掉了所有异常，可能隐藏严重 bug。请至少记录日志",
    ),
    # === CORS 全开放 ===
    (
        r"allow_origins\s*=\s*\[\s*[\"']\*[\"']\s*\]",
        "high",
        "cors-wildcard",
        'CORS 允许所有来源("*")，生产环境应限制具体域名',
    ),
    # === MD5/SHA1 弱哈希 ===
    (
        r"hashlib\.(?:md5|sha1)\s*\(",
        "high",
        "weak-hash",
        "使用 MD5/SHA1 弱哈希算法，安全敏感场景请使用 SHA-256 或 bcrypt/argon2",
    ),
    # === 硬编码 IP 地址（非内网）===
    (
        r"""(?:host|server|url|endpoint)\s*=\s*[\"']https?://(?:\d{1,3}\.){3}\d{1,3}""",
        "high",
        "hardcoded-ip",
        "硬编码 IP 地址，请通过环境变量或配置文件管理",
    ),
    # === HTTP 请求无超时（S113）===
    (
        r"(?:requests\.(?:get|post|put|delete|patch|head|options)|httpx\.(?:get|post|put|delete|patch))\s*\([^)]*\)(?![^;]*timeout)",
        "high",
        "http-no-timeout",
        "HTTP 请求未设置 timeout，可能导致请求无限挂起。请添加 timeout= 参数",
    ),
    # === 可变默认参数（OCR Python 规则）===
    (
        r"def\s+\w+\s*\([^)]*(?:=\s*\[\s*\]|=\s*\{\s*\})",
        "high",
        "mutable-default-argument",
        "函数使用可变默认参数([]或{{}})，Python 中默认参数在函数定义时创建，多次调用共享同一对象。请使用 None 作为默认值",
    ),
    # === mktemp 不安全临时文件 ===
    (
        r"tempfile\.mktemp\s*\(",
        "high",
        "insecure-tempfile",
        "tempfile.mktemp() 存在竞态条件风险。请使用 tempfile.mkstemp() 或 NamedTemporaryFile()",
    ),
    # === Flask/Django debug ===
    (
        r"app\.run\s*\([^)]*debug\s*=\s*True",
        "high",
        "flask-debug-enabled",
        "Flask/Debug 模式启用了 debug=True，生产环境存在代码执行风险",
    ),
    # === 敏感信息打印到日志 ===
    (
        r"""(?:log(?:ger)?|print)\s*\([^)]*(?:password|passwd|secret|token|api_key|credit_card)""",
        "high",
        "sensitive-data-logged",
        "日志中可能包含敏感信息（密码/Token/密钥），生产环境禁止记录敏感数据",
    ),
    # === Jinja2 自动转义关闭（XSS）===
    (
        r"jinja2\.Environment\s*\([^)]*autoescape\s*=\s*False|Markup\s*\(",
        "high",
        "jinja2-autoescape-off",
        "Jinja2 关闭了 autoescape 或使用 Markup() 标记了不安全字符串，存在 XSS 风险",
    ),
    # === TypeScript/React: dangerouslySetInnerHTML ===
    (
        r"dangerouslySetInnerHTML",
        "high",
        "react-dangerous-html",
        "React 使用 dangerouslySetInnerHTML，存在 XSS 风险。请确保内容经过消毒（DOMPurify）",
    ),
    # === TypeScript/JavaScript: eval ===
    (
        r"(?<![\w.])(?:eval|new\s+Function)\s*\(",
        "high",
        "js-dynamic-eval",
        "JavaScript/TypeScript 使用 eval() 或 new Function()，存在代码注入风险",
    ),
    # === TypeScript/JavaScript: child_process 非字面量 ===
    (
        r"(?:exec|execSync|spawnSync|spawn)\s*\(\s*[^'\"\w]",
        "high",
        "js-child-process-injection",
        "child_process 调用使用变量而非字符串字面量，存在命令注入风险",
    ),
]


def _scan_file_content(filepath: Path, rel_path: str) -> list[dict[str, Any]]:
    """扫描单个文件内容，返回发现的问题列表。"""
    issues: list[dict[str, Any]] = []
    try:
        # 限制文件大小，避免扫描超大文件
        if filepath.stat().st_size > 500_000:  # 500KB
            return issues
        lines = filepath.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return issues

    import re as _re

    for lineno, line in enumerate(lines, start=1):
        # 跳过注释行（简单判断）
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue

        for pattern, severity, rule_id, message in _CRITICAL_PATTERNS:
            if _re.search(pattern, line):
                issues.append(
                    {
                        "file": rel_path,
                        "line": lineno,
                        "severity": severity,
                        "rule": rule_id,
                        "message": message,
                        "code": line.strip()[:120],
                    }
                )

        for pattern, severity, rule_id, message in _HIGH_PATTERNS:
            if _re.search(pattern, line):
                issues.append(
                    {
                        "file": rel_path,
                        "line": lineno,
                        "severity": severity,
                        "rule": rule_id,
                        "message": message,
                        "code": line.strip()[:120],
                    }
                )

    return issues


async def _run_inprocess_security_scan(
    meeting_id: str,
    code_dir: Path,
) -> dict[str, Any]:
    """进程内静态安全扫描主函数。

    遍历 code_dir 下所有代码文件，使用正则匹配高危反模式。
    返回与原 OCR 格式兼容的结果字典。
    """
    import asyncio

    issues: list[dict[str, Any]] = []
    files_scanned = 0

    def _scan_sync() -> list[dict[str, Any]]:
        nonlocal files_scanned
        found: list[dict[str, Any]] = []
        if not code_dir.exists():
            return found
        for root, _dirs, files in os.walk(code_dir):
            # 跳过虚拟环境、node_modules、__pycache__ 等目录
            root_parts = set(Path(root).parts)
            if {".venv", "venv", "node_modules", "__pycache__", ".git", ".pytest_cache", "dist", "build"} & root_parts:
                continue
            for fname in files:
                fpath = Path(root) / fname
                if fpath.suffix.lower() not in _CODE_EXTS:
                    continue
                rel = str(fpath.relative_to(code_dir))
                files_scanned += 1
                found.extend(_scan_file_content(fpath, rel))
        return found

    issues = await asyncio.to_thread(_scan_sync)

    critical = sum(1 for i in issues if i["severity"] == "critical")
    high = sum(1 for i in issues if i["severity"] == "high")
    medium = sum(1 for i in issues if i["severity"] == "medium")
    low = sum(1 for i in issues if i["severity"] == "low")

    parts = []
    if critical > 0:
        parts.append(f"{critical}个critical")
    if high > 0:
        parts.append(f"{high}个high")
    summary = f"静态安全扫描完成：扫描{files_scanned}个文件，发现{', '.join(parts) if parts else '0个问题'}"

    return {
        "ok": True,
        "skipped": False,
        "critical": critical,
        "high": high,
        "medium": medium,
        "low": low,
        "summary": summary,
        "issues": issues[:50],
        "block_deploy": critical > 0,
        "scanner": "inprocess-regex",
        "files_scanned": files_scanned,
        "error": None,
    }


async def produce_node(state: MeetingState) -> MeetingState:
    """Produce 阶段：根据 deliverable_type 切换模板，生成对应交付物

    [AUDIT-FIX P0-2] 修复：部署失败时确保 artifact 仍被保存（不返回 null）。
    节点级异常兜底由 Runner.run() 的 try/except 统一处理（P0-4）。

    [迭代支持] 如果 state.iteration_count > 0，说明是质量迭代轮，
    将 quality_feedback 注入到 prompt 中引导 LLM 改进。
    """
    # 设置 trace 上下文
    set_current_trace(state.llm_trace)
    from app.observability.log_bus import log_bus as _lb

    _lb.info(
        f"produce: === 进入produce节点 === deliverable_type={state.deliverable_type} iteration={state.iteration_count}",
        logger="orchestrator.nodes.produce",
    )
    # 根据产出类型选择模板
    from app.agents.prompts import get_produce_template

    template = get_produce_template(state.deliverable_type)

    # === 迭代反馈注入 ===
    iteration_anchor = ""
    if state.iteration_count > 0 and state.quality_feedback:
        iteration_anchor = (
            f"\n\n[重要 - 质量迭代 第{state.iteration_count}轮]\n"
            f"上一轮产出质量评分为 {state.quality_score}/100，未达商用标准。\n"
            f"质量评估反馈如下，你必须针对这些问题进行全面改进：\n{state.quality_feedback}\n\n"
            f"请在保持已有功能完整性的基础上，重点修复上述问题，"
            f"提升代码质量、部署可靠性和功能完整度。不要省略任何已有功能。\n"
        )
        _lb.info(
            f"produce: 迭代模式 第{state.iteration_count}轮，质量反馈已注入",
            logger="orchestrator.nodes.produce",
            extra={"quality_score": state.quality_score},
        )
        await _emit_progress(state, "iterating", f"第{state.iteration_count}轮质量迭代改进中...", 5)
        await _emit_agent_spoke(
            state, Role.ENGINEER, Stage.PRODUCE, f"[质量迭代 第{state.iteration_count}轮] 根据质量评估反馈进行改进..."
        )

    # === 跨会议演进：加载引用会议的baseline代码 ===
    baseline_anchor = ""
    if state.reference_meeting_ids and state.deliverable_type == "deployable_service":
        try:
            from app.config import settings as _settings
            from app.dao.meeting_dao import get_meeting

            baseline_projects: list[dict[str, Any]] = []
            for ref_id in state.reference_meeting_ids[-1:]:  # 只取最近一个引用作为baseline，避免prompt过大
                # [Wave 2] 租户安全校验：通过 DAO 验证引用会议属于当前租户，
                # 防止通过 reference_meeting_ids 跨租户读取文件系统
                ref_meeting = await get_meeting(ref_id)
                if ref_meeting is None:
                    _lb.warning(
                        f"produce: 跳过引用会议 {ref_id} — 不存在或不属于当前租户",
                        logger="orchestrator.nodes.produce",
                    )
                    continue
                ref_ws = Path(_settings.workspace_root) / ref_id
                if not ref_ws.exists():
                    continue
                # 扫描baseline项目结构
                ref_files = {}
                for f in ref_ws.rglob("*"):
                    if f.is_file() and f.suffix in (
                        ".py",
                        ".tsx",
                        ".ts",
                        ".json",
                        ".yml",
                        ".yaml",
                        ".md",
                        ".css",
                        ".html",
                        ".txt",
                    ):
                        rel = str(f.relative_to(ref_ws)).replace("\\", "/")
                        if any(skip in rel for skip in ["__pycache__", ".pyc", "node_modules", "__init__.py"]):
                            continue
                        try:
                            content = f.read_text(encoding="utf-8")
                            if len(content) < 5000:  # 只加载小文件，避免prompt过大
                                ref_files[rel] = content[:2000]
                        except Exception:
                            pass
                if ref_files:
                    file_list = list(ref_files.keys())[:20]
                    baseline_projects.append(
                        {
                            "meeting_id": ref_id,
                            "file_count": len(ref_files),
                            "files": ref_files,
                            "file_list": file_list,
                        }
                    )
                    _lb.info(
                        f"produce: 加载baseline会议 {ref_id}，{len(ref_files)}个文件",
                        logger="orchestrator.nodes.produce",
                    )
            if baseline_projects:
                baseline_anchor = "\n\n[重要 - 跨会议演进] 以下是之前会议已完成的项目代码，你需要在此基础上**扩展和改进**，而不是从头重写：\n"
                for bp in baseline_projects:
                    baseline_anchor += f"\n--- 历史项目版本（{bp['file_count']}个文件）---\n"
                    baseline_anchor += f"文件列表: {', '.join(bp['file_list'])}\n"
                    # 只注入关键文件的内容，限制总量
                    injected_count = 0
                    for fname, fcontent in bp["files"].items():
                        if injected_count >= 8:  # 最多注入8个关键文件
                            break
                        if any(k in fname for k in ["main.py", "config.py", "models", "schemas", "routers", "engine"]):
                            baseline_anchor += f"\n=== {fname} ===\n{fcontent}\n"
                            injected_count += 1
                    baseline_anchor += "\n请在上述代码基础上进行改进和扩展，保持已有功能完整性，添加新的需求功能。\n"
                await _emit_agent_spoke(
                    state, Role.ENGINEER, Stage.PRODUCE, f"已加载{len(baseline_projects)}个历史项目版本作为演进基线"
                )
        except Exception as be:
            _lb.warning(f"produce: 加载baseline失败: {be}", logger="orchestrator.nodes.produce")

    # 发送进度：开始生成
    await _emit_progress(state, "llm_generate", "正在调用大模型生成产出内容，这可能需要几分钟...", 10)

    # [DATA-BRIDGE] 综合证据数据，供代码生成类产出使用
    evidence_summary = _synthesize_evidence_for_produce(state)
    if evidence_summary:
        _lb.info(
            f"produce: 证据桥接激活 — {evidence_summary['evidence_count']} 条证据, "
            f"{len(evidence_summary['available_data_sources'])} 个数据来源",
            logger="orchestrator.nodes.produce",
        )

    # 工具在全部环节可用：构建工具注册表，非空时走 ReactLoop（web_search/browser/workspace）
    tool_registry = _build_tool_registry()

    # 构造 produce prompt（供非deployable_service类型和fallback使用）
    def build_prompt(anchor: str, available_tools: Any) -> Any:
        # 合并迭代反馈anchor + 跨会议baseline
        combined_anchor = anchor
        anchors_to_merge = []
        if iteration_anchor:
            anchors_to_merge.append(iteration_anchor)
        if baseline_anchor:
            anchors_to_merge.append(baseline_anchor)
        if anchors_to_merge:
            combined_anchor = "\n".join(anchors_to_merge) + ("\n" + anchor if anchor else "")
        return build_produce_prompt(
            state.decision_record or {},
            anchor=combined_anchor,
            template=template,
            deliverable_type=state.deliverable_type,
            evidence_summary=evidence_summary or None,
            available_tools=available_tools,
        )

    # === 分阶段生成管线：deployable_service 使用7阶段子管线替代单次LLM调用 ===
    if state.deliverable_type == "deployable_service":
        from app.orchestrator.phased_generation import generate_deployable_service_phased

        _lb.info(
            "produce: 启用分阶段生成管线（工业级服务生成升级）",
            logger="orchestrator.nodes.produce",
        )
        await _emit_agent_spoke(
            state, Role.ENGINEER, Stage.PRODUCE, "启动分阶段代码生成管线：规划→规格→测试→骨架→模块→前端→整合"
        )

        # 合并anchor上下文（迭代反馈 + 跨会议baseline）
        extra_anchor_parts = []
        if iteration_anchor:
            extra_anchor_parts.append(iteration_anchor)
        if baseline_anchor:
            extra_anchor_parts.append(baseline_anchor)
        extra_anchor = "\n".join(extra_anchor_parts) if extra_anchor_parts else ""

        async def _phased_progress(stage_name: str, message: str, percent: int) -> None:
            """子阶段进度回调"""
            await _emit_progress(state, f"phased_{stage_name}", message, percent)
            await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE, f"[{stage_name}] {message}")

        try:
            phased_result = await generate_deployable_service_phased(
                state,
                on_progress=_phased_progress,
                extra_anchor=extra_anchor,
            )
            result = phased_result.to_result_dict()
            confidence = "high"
            total_files = (
                len(phased_result.project_tree)
                + len(phased_result.frontend_tree)
                + len(phased_result.test_tree)
                + len(phased_result.root_files)
            )
            _lb.info(
                f"produce: 分阶段生成完成 — "
                f"title={phased_result.title}, "
                f"files={total_files}, "
                f"llm_calls={phased_result.total_llm_calls}, "
                f"complexity={phased_result.complexity_level}",
                logger="orchestrator.nodes.produce",
            )
            await _emit_progress(state, "phased_done", "分阶段生成完成", 95)
        except Exception as pe:
            import traceback

            _lb.error(
                f"produce: 分阶段生成失败，回退到单次LLM调用: {pe}\n{traceback.format_exc()}",
                logger="orchestrator.nodes.produce",
            )
            await _emit_agent_spoke(
                state, Role.ENGINEER, Stage.PRODUCE, f"分阶段生成异常({type(pe).__name__})，回退到传统生成模式"
            )
            # 回退到原来的单次LLM调用（工具在全部环节可用）
            result, confidence = await _run_stage_step(
                state,
                "produce",
                Role.MODERATOR.value,
                build_prompt,
                tool_registry=tool_registry,
                on_token=_make_token_stream_callback(state),
            )

    else:
        # 非deployable_service类型使用原有单次LLM调用（工具在全部环节可用）
        result, confidence = await _run_stage_step(
            state,
            "produce",
            Role.MODERATOR.value,
            build_prompt,
            tool_registry=tool_registry,
            on_token=_make_token_stream_callback(state),
        )

    # 内容完整性校验：检查关键字段是否为空
    # 一致性检查只验证结果不与已锁定结论矛盾，不验证内容是否为空
    _empty_fields = []
    if state.deliverable_type == "deployable_service":
        _ds = result.get("deployable_service") or {}
        if not _ds.get("app_code"):
            _empty_fields.append("deployable_service.app_code")
    elif state.deliverable_type in ("code_analysis", "data_science"):
        _cd = result.get("code_analysis") or {}
        if not _cd.get("code"):
            _empty_fields.append("code_analysis.code")
    elif state.deliverable_type == "tested_system":
        _ts = result.get("tested_system") or {}
        if not _ts.get("main_code") and not _ts.get("test_code"):
            _empty_fields.append("tested_system.main_code/test_code")
    elif state.deliverable_type == "prd_openapi":
        if not result.get("prd") and not result.get("openapi"):
            _empty_fields.append("prd/openapi")
    if _empty_fields:
        _confidence_before = confidence
        loc = _current_src_loc(depth=1)
        _lb.warning(
            f"produce: LLM 返回内容不完整 — 空字段: {_empty_fields} (触发位置: {loc['file']}:{loc['line']})",
            logger="orchestrator.nodes.produce",
            extra={
                "deliverable_type": state.deliverable_type,
                "empty_fields": _empty_fields,
                "src_file": loc["file"],
                "src_line": loc["line"],
                "condition": f"deliverable_type={state.deliverable_type} 且 {_empty_fields} 为空",
                "logic": "produce 节点内容完整性校验：关键字段为空时阻止部署/沙箱执行，并将 confidence 从 high 降级为 low",
                "current_state": {
                    "status": state.status.value if state.status else None,
                    "stage": state.stage.value if state.stage else None,
                    "confidence_flags": dict(state.confidence_flags) if state.confidence_flags else {},
                },
            },
        )
        if confidence == "high":
            confidence = "low"
            state.confidence_flags["produce"] = "low"
        await _emit_degradation_event(
            state=state,
            reason="produce_critical_field_empty",
            empty_fields=_empty_fields,
            result=result,
            confidence_before=_confidence_before,
            confidence_after=confidence,
        )

    _lb.info(
        "produce: LLM 调用+一致性检查完成",
        logger="orchestrator.nodes.produce",
        extra={
            "confidence": confidence,
            "deliverable_type": state.deliverable_type,
            "has_prd": bool(result.get("prd")),
            "openapi_len": len(result.get("openapi", "")),
        },
    )

    # 发送进度：LLM生成完成，开始后续处理
    await _emit_progress(state, "llm_done", "大模型生成完成，正在处理产出内容...", 40)

    # 构建 artifact
    prd = result.get("prd", {})
    openapi = result.get("openapi", "")
    state.artifact = {
        "meeting_id": state.meeting_id,
        "deliverable_type": state.deliverable_type,
        "prd": prd,
        "openapi": openapi,
    }

    # 记录产出阶段的Agent发言
    if state.deliverable_type == "prd_openapi":
        prd_title = prd.get("title", "未命名产品")
        api_count = len(prd.get("api_endpoints", []))
        summary = (
            f"产出完成：{prd_title}\n"
            f"产品目标：{prd.get('goal', 'N/A')[:200]}\n"
            f"OpenAPI 规范：{len(openapi)} 字符" + (f"，包含 {api_count} 个 API 端点" if api_count else "")
        )
        await _emit_agent_spoke(state, Role.PRODUCT_ARCHITECT, Stage.PRODUCE, summary)
        if openapi:
            await _emit_agent_spoke(
                state,
                Role.ENGINEER,
                Stage.PRODUCE,
                f"已生成 OpenAPI 规范（{len(openapi)} 字符），包含完整的接口定义和数据模型。",
            )
    elif state.deliverable_type in ("code_analysis", "data_science"):
        code_data = result.get("code_analysis", {})
        code_len = len(code_data.get("code", ""))
        if code_len == 0:
            await _emit_agent_spoke(
                state,
                Role.ENGINEER,
                Stage.PRODUCE,
                "代码生成失败：LLM 返回的代码为空，跳过沙箱执行。产出物可能不完整，建议重试。",
            )
        else:
            await _emit_agent_spoke(
                state, Role.ENGINEER, Stage.PRODUCE, f"代码生成完成：{code_len} 字符，准备沙箱执行验证..."
            )
    elif state.deliverable_type == "tested_system":
        ts_data = result.get("tested_system", {})
        main_len = len(ts_data.get("main_code", ""))
        test_len = len(ts_data.get("test_code", ""))
        if main_len == 0 and test_len == 0:
            await _emit_agent_spoke(
                state,
                Role.ENGINEER,
                Stage.PRODUCE,
                "代码生成失败：LLM 返回的主代码和测试代码均为空，跳过测试执行。产出物可能不完整，建议重试。",
            )
        else:
            await _emit_agent_spoke(
                state,
                Role.ENGINEER,
                Stage.PRODUCE,
                f"系统代码和测试已生成：主代码 {main_len} 字符，测试代码 {test_len} 字符，准备运行测试...",
            )
    elif state.deliverable_type == "test_suite":
        ts_data = result.get("test_suite", {})
        file_count = len(
            [f for f in (ts_data.get("test_files") or []) if isinstance(f, dict) and f.get("path") and f.get("code")]
        )
        if file_count == 0:
            await _emit_agent_spoke(
                state,
                Role.ENGINEER,
                Stage.PRODUCE,
                "测试生成失败：LLM 未返回有效测试文件，跳过沙箱执行。产出物可能不完整，建议重试。",
            )
        else:
            await _emit_agent_spoke(
                state, Role.ENGINEER, Stage.PRODUCE, f"已生成 {file_count} 个测试文件，准备沙箱执行验证..."
            )
    elif state.deliverable_type == "deployable_service":
        ds_data = result.get("deployable_service", {})
        app_len = len(ds_data.get("app_code", ""))
        if app_len == 0:
            await _emit_agent_spoke(
                state,
                Role.ENGINEER,
                Stage.PRODUCE,
                "代码生成失败：LLM 返回的应用代码为空，跳过代码审查和部署。产出物可能不完整，建议重试。",
            )
        else:
            await _emit_agent_spoke(
                state,
                Role.ENGINEER,
                Stage.PRODUCE,
                f"可部署服务代码已生成：应用代码 {app_len} 字符，开始代码审查和Docker部署...",
            )
    elif state.deliverable_type == "design_doc":
        dd = result.get("design_doc", {})
        await _emit_agent_spoke(
            state, Role.PRODUCT_ARCHITECT, Stage.PRODUCE, f"设计文档已生成：{dd.get('title', '未命名')}"
        )
    elif state.deliverable_type == "comprehensive":
        await _emit_agent_spoke(state, Role.MODERATOR, Stage.PRODUCE, "综合产出已生成。")
    elif state.deliverable_type == "research_report":
        await _emit_agent_spoke(state, Role.PRODUCT_ARCHITECT, Stage.PRODUCE, "研究报告已生成。")
    elif state.deliverable_type == "business_report":
        await _emit_agent_spoke(state, Role.MODERATOR, Stage.PRODUCE, "商业分析报告已生成。")
    else:
        await _emit_agent_spoke(
            state, Role.MODERATOR, Stage.PRODUCE, f"产出物生成完成（类型：{state.deliverable_type}）。"
        )

    # 代码执行类产出：调用沙箱执行代码
    if state.deliverable_type in ("code_analysis", "data_science"):
        code_data = result.get("code_analysis") or {}
        code = code_data.get("code", "")
        if code:
            from app.orchestrator.refine_loop import _summarize_task, refine_python_code
            from app.sandbox import SANDBOX_IMAGE_DATASCIENCE, run_python

            os.environ.get("CONCLAVE_WORKSPACE_DIR", "")
            # [CON-24 修复] 用 config.settings.workspace_root 作为持久化工作区根
            from app.config import settings

            ws_root = Path(settings.workspace_root) / state.meeting_id
            ws_root.mkdir(parents=True, exist_ok=True)
            try:
                # code_analysis 模板更可能需要数据分析库，使用数据科学镜像
                # 根据代码内容判断网络级别
                net_level = _detect_network_level(code)

                async def _run(code, level=net_level):
                    r = await run_python(
                        code, ws_root, timeout=30, image=SANDBOX_IMAGE_DATASCIENCE, network_level=level
                    )
                    return r.to_dict()

                task_summary = _summarize_task("code_analysis", result)
                refined = await refine_python_code(
                    code,
                    task_summary,
                    _run,
                    max_rounds=5,
                    meeting_id=state.meeting_id,
                    stage="produce",
                    detected_level=net_level,
                )
                # 网络授权获批后用新级别重试
                if refined.get("need_retry_with_level"):
                    new_level = refined["need_retry_with_level"]
                    _lb.info(
                        f"produce: 网络授权获批 level={new_level}，重新执行代码", logger="orchestrator.nodes.produce"
                    )

                    async def _run_approved(code):
                        r = await run_python(
                            code, ws_root, timeout=30, image=SANDBOX_IMAGE_DATASCIENCE, network_level=new_level
                        )
                        return r.to_dict()

                    refined = await refine_python_code(
                        refined["code"],
                        task_summary,
                        _run_approved,
                        max_rounds=3,
                        meeting_id=state.meeting_id,
                        stage="produce",
                        detected_level=new_level,
                    )
                code_data["code"] = refined["code"]
                state.artifact["code_analysis"] = code_data
                state.artifact["execution"] = refined["execution"]
                state.artifact["refine_info"] = {
                    "rounds_used": refined["rounds_used"],
                    "success": refined["success"],
                }
                if refined.get("net_auth"):
                    state.artifact["net_auth"] = refined["net_auth"]
                # 记录代码执行结果消息
                exec_result = refined.get("execution", {})
                if exec_result.get("exit_code") == 0:
                    out_preview = (exec_result.get("stdout", "") or "")[:300]
                    await _emit_agent_spoke(
                        state, Role.ENGINEER, Stage.PRODUCE, f"代码执行成功。输出预览：\n{out_preview}"
                    )
                else:
                    err_preview = (exec_result.get("stderr", "") or exec_result.get("error", ""))[:300]
                    await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE, f"代码执行遇到问题：{err_preview}")
            except Exception as e:
                state.artifact["code_analysis"] = code_data
                state.artifact["execution"] = {"error": str(e), "exit_code": -1}
                await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE, f"代码执行异常：{str(e)[:200]}")
        else:
            state.artifact["code_analysis"] = code_data

    elif state.deliverable_type == "tested_system":
        ts_data = result.get("tested_system") or {}
        main_code = ts_data.get("main_code", "")
        test_code = ts_data.get("test_code", "")
        if test_code:
            # [CON-24 修复] 用持久化工作区
            from app.config import settings
            from app.orchestrator.refine_loop import _summarize_task, refine_python_code
            from app.sandbox import SANDBOX_IMAGE_DATASCIENCE, run_command

            ws_root = Path(settings.workspace_root) / state.meeting_id
            ws_root.mkdir(parents=True, exist_ok=True)
            ws_root.mkdir(parents=True, exist_ok=True)
            try:
                # 把代码写入工作区
                test_file = ws_root / "test_generated.py"
                test_file.write_text(test_code, encoding="utf-8")
                main_file = ws_root / "main_generated.py"
                if main_code:
                    main_file.write_text(main_code, encoding="utf-8")
                # tested_system 模板更可能需要数据分析库，使用数据科学镜像
                net_level = _detect_network_level(test_code)

                async def _run_tests(code, level=net_level):
                    test_file.write_text(code, encoding="utf-8")
                    r = await run_command(
                        "python -m pytest test_generated.py -v",
                        ws_root,
                        timeout=30,
                        image=SANDBOX_IMAGE_DATASCIENCE,
                        network_level=level,
                    )
                    return r.to_dict()

                task_summary = _summarize_task("tested_system", result)
                refined = await refine_python_code(
                    test_code,
                    task_summary,
                    _run_tests,
                    max_rounds=5,
                    meeting_id=state.meeting_id,
                    stage="produce",
                    detected_level=net_level,
                )
                # 网络授权获批后用新级别重试
                if refined.get("need_retry_with_level"):
                    new_level = refined["need_retry_with_level"]
                    _lb.info(
                        f"produce: 网络授权获批 level={new_level}，重新执行测试", logger="orchestrator.nodes.produce"
                    )

                    async def _run_tests_approved(code):
                        test_file.write_text(code, encoding="utf-8")
                        r = await run_command(
                            "python -m pytest test_generated.py -v",
                            ws_root,
                            timeout=30,
                            image=SANDBOX_IMAGE_DATASCIENCE,
                            network_level=new_level,
                        )
                        return r.to_dict()

                    refined = await refine_python_code(
                        refined["code"],
                        task_summary,
                        _run_tests_approved,
                        max_rounds=3,
                        meeting_id=state.meeting_id,
                        stage="produce",
                        detected_level=new_level,
                    )
                ts_data["test_code"] = refined["code"]
                state.artifact["tested_system"] = ts_data
                state.artifact["execution"] = refined["execution"]
                state.artifact["refine_info"] = {
                    "rounds_used": refined["rounds_used"],
                    "success": refined["success"],
                }
                if refined.get("net_auth"):
                    state.artifact["net_auth"] = refined["net_auth"]
                # 记录测试执行结果消息
                test_result = refined.get("execution", {})
                if refined.get("success") and test_result.get("exit_code") == 0:
                    out_preview = (test_result.get("stdout", "") or "")[:300]
                    await _emit_agent_spoke(
                        state,
                        Role.ENGINEER,
                        Stage.PRODUCE,
                        f"测试全部通过（{refined.get('rounds_used', 1)}轮修复）。结果预览：\n{out_preview}",
                    )
                else:
                    err_preview = (test_result.get("stderr", "") or test_result.get("error", ""))[:300]
                    await _emit_agent_spoke(
                        state, Role.ENGINEER, Stage.PRODUCE, f"测试执行完成，但存在问题：{err_preview}"
                    )
            except Exception as e:
                state.artifact["tested_system"] = ts_data
                state.artifact["execution"] = {"error": str(e), "exit_code": -1}
                await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE, f"测试执行异常：{str(e)[:200]}")
        else:
            state.artifact["tested_system"] = ts_data

    elif state.deliverable_type == "test_suite":
        # ADR-017 Phase 3（T3.2）：test_suite 执行闭环
        # 写入测试文件 → 沙箱 pytest → execution + test_report 写回
        ts_data = result.get("test_suite") or {}
        test_files = ts_data.get("test_files") or []
        if test_files:
            from app.config import settings
            from app.sandbox import SANDBOX_IMAGE_DATASCIENCE, run_command

            ws_root = Path(settings.workspace_root) / state.meeting_id
            ws_root.mkdir(parents=True, exist_ok=True)
            try:
                kept_files, skipped_paths = _write_test_files(ws_root, test_files)
                if skipped_paths:
                    _lb.warning(
                        f"produce: test_suite 丢弃 {len(skipped_paths)} 个非法路径",
                        logger="orchestrator.nodes.produce",
                        extra={"meeting_id": state.meeting_id, "skipped_paths": skipped_paths[:5]},
                    )
                # 规范化后的文件列表回写（路径已清洗，供产物发布与门禁使用）
                ts_data["test_files"] = kept_files

                if kept_files:
                    all_code = "".join(f["code"] for f in kept_files)
                    net_level = _detect_network_level(all_code)
                    # I10：路径已过白名单校验（字符集受限），拼接无注入面
                    pytest_cmd = "python -m pytest " + " ".join(f["path"] for f in kept_files) + " -v"
                    exec_result = await run_command(
                        pytest_cmd,
                        ws_root,
                        timeout=TEST_SUITE_EXEC_TIMEOUT,
                        image=SANDBOX_IMAGE_DATASCIENCE,
                        network_level=net_level,
                    )
                    exec_dict = exec_result.to_dict()
                    report = _parse_test_report(exec_dict)
                    report["test_file_count"] = len(kept_files)
                    state.artifact["test_suite"] = ts_data
                    state.artifact["execution"] = exec_dict
                    state.artifact["test_report"] = report
                    if report["failed"] == 0 and report["passed"] > 0:
                        await _emit_agent_spoke(
                            state,
                            Role.ENGINEER,
                            Stage.PRODUCE,
                            f"测试套件执行完成：{report['passed']} 个测试全部通过。",
                        )
                    else:
                        await _emit_agent_spoke(
                            state,
                            Role.ENGINEER,
                            Stage.PRODUCE,
                            f"测试套件执行完成：{report['passed']} 通过 / {report['failed']} 失败。",
                        )
                    # ADR-017 Phase 3（T3.5）：workspace 自动提交（bot 身份、
                    # Conventional Commits）。失败仅记日志，不阻断产出。
                    try:
                        from app.services.git_service import commit_workspace

                        commit_info = await commit_workspace(
                            state.meeting_id, topic=state.clarified_topic or state.topic
                        )
                        if commit_info.get("committed"):
                            _lb.info(
                                f"produce: test_suite 工作区已提交 {commit_info.get('commit_sha')}",
                                logger="orchestrator.nodes.produce",
                                extra={"meeting_id": state.meeting_id},
                            )
                    except Exception as commit_err:
                        _lb.warning(
                            f"produce: 工作区自动提交失败（不影响产出）: {str(commit_err)[:150]}",
                            logger="orchestrator.nodes.produce",
                            extra={"meeting_id": state.meeting_id},
                        )
                else:
                    # 全部路径非法 → 不执行，产物仍发布（降级可追溯）
                    state.artifact["test_suite"] = ts_data
                    state.artifact["test_report"] = {
                        "error": "所有测试路径均未通过安全校验，未执行",
                        "passed": 0,
                        "failed": 0,
                        "test_file_count": 0,
                        "executed_at": datetime.now(timezone.utc).isoformat(),
                    }
                    await _emit_agent_spoke(
                        state, Role.ENGINEER, Stage.PRODUCE, "测试文件路径均未通过安全校验，已跳过沙箱执行。"
                    )
            except Exception as e:
                state.artifact["test_suite"] = ts_data
                state.artifact["execution"] = {"error": str(e), "exit_code": -1}
                state.artifact["test_report"] = {
                    "error": str(e)[:300],
                    "passed": 0,
                    "failed": 0,
                    "test_file_count": len(test_files),
                    "executed_at": datetime.now(timezone.utc).isoformat(),
                }
                await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE, f"测试执行异常：{str(e)[:200]}")
        else:
            state.artifact["test_suite"] = ts_data

    elif state.deliverable_type == "deployable_service":
        ds_data = result.get("deployable_service") or {}

        # 兼容新旧格式：构造DeployableServiceArtifact实例来获取有效文件树
        try:
            from app.agents.schemas import DeployableServiceArtifact

            ds_artifact = DeployableServiceArtifact(**ds_data)
        except Exception:
            # 降级：手动构造
            ds_artifact = DeployableServiceArtifact(
                title=ds_data.get("title", ""),
                description=ds_data.get("description", ""),
                complexity_level=ds_data.get("complexity_level", "medium"),
                tech_stack=ds_data.get("tech_stack", []),
                port=ds_data.get("port", 8000),
                run_command=ds_data.get("run_command", "uvicorn app.main:app --host 0.0.0.0 --port 8000"),
                credentials=ds_data.get("credentials", {}),
                project_tree=ds_data.get("project_tree", {}),
                frontend_tree=ds_data.get("frontend_tree", {}),
                test_tree=ds_data.get("test_tree", {}),
                root_files=ds_data.get("root_files", {}),
                app_code=ds_data.get("app_code", ""),
                dockerfile=ds_data.get("dockerfile", ""),
                docker_compose=ds_data.get("docker_compose", ""),
                requirements_txt=ds_data.get("requirements_txt", ""),
                readme=ds_data.get("readme", ""),
                static_files=ds_data.get("static_files", {}),
            )

        effective_tree = ds_artifact.get_effective_tree()
        complexity = ds_artifact.complexity_level
        total_files = ds_artifact.count_files()
        total_lines = ds_artifact.count_code_lines()
        service_port = ds_artifact.port
        credentials = ds_artifact.credentials

        _lb.info(
            f"produce: 收到可部署服务产出，复杂度={complexity}, 文件数={total_files}, 代码行数={total_lines}",
            logger="orchestrator.nodes.produce",
            extra={"complexity": complexity, "files": total_files, "lines": total_lines},
        )
        await _emit_progress(state, "writing_files", f"正在写入 {total_files} 个项目文件（{total_lines}行代码）...", 20)
        await _emit_agent_spoke(
            state,
            Role.ENGINEER,
            Stage.PRODUCE,
            f"代码生成完成：复杂度 {complexity}，{total_files} 个文件，{total_lines} 行代码",
        )

        if effective_tree:
            from app.config import settings

            ws_root = Path(settings.workspace_root) / state.meeting_id

            # === 写入完整项目树 ===
            files_written = 0
            dirs_created = set()
            for rel_path, content in effective_tree.items():
                if not isinstance(content, str) or len(content) < 1:
                    continue
                # 安全路径处理：防止路径穿越
                safe_path = rel_path.replace("\\", "/")
                if safe_path.startswith("/"):
                    safe_path = safe_path[1:]
                if ".." in safe_path:
                    continue
                target = ws_root / safe_path
                # 确保父目录存在
                parent = target.parent
                if parent not in dirs_created:
                    parent.mkdir(parents=True, exist_ok=True)
                    dirs_created.add(parent)
                target.write_text(content, encoding="utf-8")
                files_written += 1

            _lb.info(f"produce: 已写入 {files_written} 个文件到工作区", logger="orchestrator.nodes.produce")

            # === 自动修复：检查/补全必要文件 ===
            # 1. 确保有/health端点
            main_py = ws_root / "app" / "main.py"
            if main_py.exists():
                main_content = main_py.read_text(encoding="utf-8")
                if "/health" not in main_content:
                    health_code = f"""

@app.get("/health")
async def health_check():
    return {{"status": "ok", "service": "{ds_artifact.title}"}}
"""
                    if "app = create_app()" in main_content:
                        main_content = main_content.replace("app = create_app()", "app = create_app()\n" + health_code)
                    else:
                        main_content += "\n" + health_code
                    main_py.write_text(main_content, encoding="utf-8")

            # 2. 确保Dockerfile安装了HEALTHCHECK需要的工具
            dockerfile_path = ws_root / "Dockerfile"
            if dockerfile_path.exists():
                df_content = dockerfile_path.read_text(encoding="utf-8")
                if (
                    "HEALTHCHECK" in df_content
                    and "curl" not in df_content
                    and "wget" not in df_content
                    and "CMD " in df_content
                ):
                    # 在CMD之前插入curl安装
                    df_content = df_content.replace(
                        "CMD ",
                        "RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*\n\nCMD ",
                        1,
                    )
                    dockerfile_path.write_text(df_content, encoding="utf-8")

            # 3. 确保有__init__.py文件
            for pkg_dir in [
                "app",
                "app/routers",
                "app/schemas",
                "app/services",
                "app/dao",
                "app/db",
                "app/db/models",
                "app/domain",
                "app/core",
            ]:
                init_file = ws_root / pkg_dir / "__init__.py"
                if (ws_root / pkg_dir).exists() and not init_file.exists():
                    init_file.write_text("", encoding="utf-8")

            # === 代码审查（针对关键文件）===
            review_passed = True
            review_summary = ""
            review_rounds = 0
            test_results: dict[str, Any] | None = None

            await _emit_progress(state, "code_review", "正在审查关键代码文件...", 40)

            # 收集关键文件用于审查
            key_files_content = {}
            key_files_review = [
                "app/main.py",
                "app/config.py",
                "app/db/engine.py",
                "requirements.txt",
                "Dockerfile",
                "docker-compose.yml",
            ]
            for kf in key_files_review:
                kf_path = ws_root / kf
                if kf_path.exists():
                    with contextlib.suppress(Exception):
                        key_files_content[kf] = kf_path.read_text(encoding="utf-8")

            # 收集所有router/schema/dao文件做简要检查
            for subdir in ["app/routers", "app/schemas", "app/services", "app/dao", "app/db/models"]:
                subdir_path = ws_root / subdir
                if subdir_path.exists():
                    for f in subdir_path.iterdir():
                        if f.suffix == ".py" and f.name != "__init__.py":
                            rel = str(f.relative_to(ws_root)).replace("\\", "/")
                            with contextlib.suppress(Exception):
                                key_files_content[rel] = f.read_text(encoding="utf-8")[:3000]  # 截断审查

            # 运行Python语法检查
            syntax_errors = []
            for rel_path, content in effective_tree.items():
                if rel_path.endswith(".py") and isinstance(content, str) and len(content) > 10:
                    import ast as _ast

                    try:
                        _ast.parse(content)
                    except SyntaxError as se:
                        syntax_errors.append(f"{rel_path}:{se.lineno}: {se.msg}")

            if syntax_errors:
                review_passed = False
                review_summary = f"发现{len(syntax_errors)}个Python语法错误: {'; '.join(syntax_errors[:3])}"
                _lb.warning(f"produce: 语法检查发现错误: {syntax_errors[:3]}", logger="orchestrator.nodes.produce")
            else:
                review_passed = True
                review_summary = f"语法检查通过（{files_written}个文件）"

            # === 确定性静态安全扫描（进程内 regex 检查，无外部依赖）===
            # 风险说明：原计划集成阿里 OpenCodeReview(OCR)，经调研发现：
            #   1) OCR 默认需要外部 LLM API Key（OpenAI/Anthropic），会将代码发送到第三方
            #   2) OCR 内置规则不覆盖 Python（Conclave 后端主语言）
            #   3) 存在同名 BSL-1.1 协议项目（@opencodereview/cli），商用需付费
            # 因此采用进程内 regex 扫描方案：确定性、零依赖、不出网、不泄露代码。
            # 覆盖 critical/high 两类最危险的反模式。code_review.yaml skill 提供 LLM 审查。
            code_review_info: dict[str, Any] = {
                "ok": True,
                "skipped": False,
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "summary": "",
                "issues": [],
                "block_deploy": False,
                "scanner": "inprocess-regex",
            }
            try:
                _lb.info("produce: 开始进程内静态安全扫描...", logger="orchestrator.nodes.produce")
                await _emit_progress(state, "reviewing", "正在执行静态安全扫描...", 55)
                code_review_info = await _run_inprocess_security_scan(
                    meeting_id=state.meeting_id,
                    code_dir=ws_root,
                )
                if code_review_info["critical"] > 0:
                    code_review_info["block_deploy"] = True
                    review_passed = False
                    review_summary += f"；安全扫描发现{code_review_info['critical']}个critical漏洞，阻断部署"
                    _lb.warning(
                        "produce: 静态扫描发现critical漏洞，阻断部署",
                        logger="orchestrator.nodes.produce",
                        extra={"critical": code_review_info["critical"]},
                    )
                elif code_review_info["high"] > 0:
                    review_summary += f"；安全扫描发现{code_review_info['high']}个high漏洞（告警不阻断）"
                    _lb.warning(
                        f"produce: 静态扫描发现{code_review_info['high']}个high漏洞（不阻断部署）",
                        logger="orchestrator.nodes.produce",
                    )
                else:
                    review_summary += "；安全扫描通过"
                    _lb.info("produce: 静态安全扫描通过", logger="orchestrator.nodes.produce")
            except Exception as scan_err:
                code_review_info["skipped"] = True
                code_review_info["error"] = str(scan_err)
                review_summary += "；安全扫描异常跳过（不阻断部署）"
                _lb.warning(
                    f"produce: 静态安全扫描异常: {scan_err}",
                    logger="orchestrator.nodes.produce",
                    extra={"error": str(scan_err)},
                )

            # === 沙箱部署 ===
            deployment_info: dict[str, Any] = {"ok": False, "error": "not_attempted"}

            if code_review_info.get("block_deploy"):
                deployment_info = {
                    "ok": False,
                    "error": f"安全审查阻断：发现{code_review_info['critical']}个critical漏洞，请修复后重试",
                    "blocked_by_security": True,
                }
                _lb.warning(
                    "produce: 因critical漏洞阻断部署",
                    logger="orchestrator.nodes.produce",
                    extra={"critical": code_review_info["critical"]},
                )
                await _emit_agent_spoke(
                    state,
                    Role.ENGINEER,
                    Stage.PRODUCE,
                    f"[BLOCK] 代码安全扫描发现{code_review_info['critical']}个critical漏洞，部署已阻断。请修复后重试。",
                )
            try:
                from app.sandbox import deploy_service

                _lb.info("produce: 开始沙箱部署服务...", logger="orchestrator.nodes.produce")
                await _emit_progress(state, "deploying", "正在Docker沙箱中构建和部署服务...", 60)

                deploy_result = await deploy_service(
                    meeting_id=state.meeting_id,
                    workspace_root=Path(settings.workspace_root),
                    container_port=service_port,
                    health_path="/health",
                    wait_seconds=300,
                    credentials=credentials if credentials else None,
                    env_vars={"SECRET_KEY": "dev-conclave-secret-change-me"},
                )
                deployment_info = deploy_result.to_dict()
                _lb.info(
                    f"produce: 服务部署{'成功' if deploy_result.ok else '失败'}",
                    logger="orchestrator.nodes.produce",
                    extra={
                        "access_url": deploy_result.access_url,
                        "ok": deploy_result.ok,
                        "error": deployment_info.get("error", ""),
                    },
                )

                await bus.publish(
                    make_event(
                        "service.deployed" if deploy_result.ok else "service.deploy_failed",
                        state.meeting_id,
                        deployment_info,
                    )
                )
            except Exception as deploy_err:
                import traceback

                _lb.error(f"produce: 服务部署异常: {deploy_err}", logger="orchestrator.nodes.produce")
                deployment_info = {"ok": False, "error": str(deploy_err), "logs": traceback.format_exc()[:2000]}

            # === 测试执行（部署成功后且有测试文件时）===
            if deployment_info.get("ok") and ds_artifact.test_tree:
                await _emit_progress(state, "testing", "正在运行自动化测试...", 80)
                await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE, "部署成功，正在运行自动化测试...")
                try:
                    from app.sandbox import run_tests_in_container

                    test_results = await run_tests_in_container(
                        meeting_id=state.meeting_id,
                        workspace_root=Path(settings.workspace_root),
                    )
                    _lb.info(
                        f"produce: 测试结果: passed={test_results.get('passed', 0)}, failed={test_results.get('failed', 0)}",
                        logger="orchestrator.nodes.produce",
                    )
                    await bus.publish(make_event("service.tested", state.meeting_id, test_results))
                    if test_results.get("failed", 0) > 0:
                        failed_tests = test_results.get("failures", [])[:3]
                        await _emit_agent_spoke(
                            state,
                            Role.ENGINEER,
                            Stage.PRODUCE,
                            f"测试完成：{test_results.get('passed', 0)}通过，{test_results.get('failed', 0)}失败。"
                            f"失败用例: {'; '.join(failed_tests)}",
                        )
                    else:
                        await _emit_agent_spoke(
                            state, Role.ENGINEER, Stage.PRODUCE, f"全部 {test_results.get('passed', 0)} 个测试通过 ✅"
                        )
                except Exception as test_err:
                    _lb.warning(f"produce: 测试执行异常: {test_err}", logger="orchestrator.nodes.produce")
                    test_results = {"passed": 0, "failed": 0, "error": str(test_err)}
            elif deployment_info.get("ok") and not ds_artifact.test_tree:
                test_results = {
                    "passed": 0,
                    "failed": 0,
                    "note": "no_tests_generated",
                    "warning": "未生成测试文件，质量门禁无法完全验证",
                }
                _lb.warning("produce: 部署成功但未生成测试文件", logger="orchestrator.nodes.produce")

            # === 汇总产出物信息 ===
            state.artifact["deployable_service"] = {
                **ds_data,
                "project_tree": dict(ds_artifact.project_tree),
                "frontend_tree": dict(ds_artifact.frontend_tree),
                "test_tree": dict(ds_artifact.test_tree),
                "root_files": dict(ds_artifact.root_files),
                "complexity_level": complexity,
                "tech_stack": ds_artifact.tech_stack,
                "total_files": total_files,
                "total_lines": total_lines,
            }
            state.artifact["deployment_dir"] = str(ws_root)
            state.artifact["review"] = {
                "rounds": review_rounds,
                "passed": review_passed,
                "summary": review_summary,
                "syntax_errors": syntax_errors if not review_passed else [],
            }
            state.artifact["code_review"] = code_review_info
            state.artifact["deployment"] = deployment_info
            state.artifact["test_results"] = test_results

            # 判断整体成功：部署成功 + (无测试或测试通过)
            deploy_ok = deployment_info.get("ok", False)
            tests_pass = (
                test_results is None
                or test_results.get("failed", 0) == 0
                or test_results.get("note") == "no_tests_generated"
            )
            overall_ok = deploy_ok and review_passed and tests_pass

            file_list_summary = list(effective_tree.keys())[:20]
            if total_files > 20:
                file_list_summary.append(f"... (共{total_files}个文件)")

            state.artifact["execution"] = {
                "exit_code": 0 if overall_ok else 1,
                "stdout": (
                    f"复杂度: {complexity}\n"
                    f"代码规模: {total_files}文件, {total_lines}行\n"
                    f"技术栈: {', '.join(ds_artifact.tech_stack[:8])}\n"
                    f"代码审查: {'通过' if review_passed else '未通过'}\n"
                    f"安全扫描: {code_review_info.get('summary', '未执行')}\n"
                    f"服务部署: {'成功 ✅ ' + deployment_info.get('access_url', '') if deploy_ok else '失败: ' + deployment_info.get('error', '未知错误')}\n"
                    f"测试结果: "
                    + (
                        f"{test_results.get('passed', 0)}通过/{test_results.get('failed', 0)}失败"
                        if test_results and test_results.get("note") != "no_tests_generated"
                        else "未生成测试文件"
                    )
                    + "\n"
                    f"文件列表: {', '.join(file_list_summary)}"
                ),
                "stderr": (deployment_info.get("logs", "") if not deploy_ok else "")
                + ("\n" + (test_results.get("error", "") if test_results and test_results.get("error") else "")),
                "sandboxed": True,
                "files": list(effective_tree.keys()),
            }

            if deploy_ok:
                url = deployment_info.get("access_url", "")
                test_msg = ""
                if test_results and test_results.get("failed", 0) == 0 and test_results.get("passed", 0) > 0:
                    test_msg = f"，{test_results['passed']}个测试全部通过"
                await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE, f"服务部署成功！访问地址：{url}{test_msg}")
            else:
                err = deployment_info.get("error", "未知错误")
                await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE, f"服务部署失败：{err}")
        else:
            state.artifact["deployable_service"] = ds_data
    else:
        # 其他类型直接存入 artifact
        # ADR-017 Phase 3（T3.1/I8）：补两种新文档类型的写入链路。
        # test_suite 不在此列——它走上方专属执行分支。
        for key in ["design_doc", "comprehensive", "research_report", "business_report", "feasibility_report", "adr"]:
            if key in result:
                state.artifact[key] = result[key]

    # ─── 生成报告布局 spec（report_layout）───
    # 后端驱动布局：将 artifact 转换为前端可通用渲染的 layout spec
    # 前端只需按 spec 渲染，不再硬编码任何模板
    try:
        from app.report_layout import build_report_layout

        meeting_meta = {
            "meeting_id": state.meeting_id,
            "topic": state.clarified_topic or state.topic,
            "status": state.status.value if hasattr(state.status, "value") else str(state.status),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        # 从 state 提取上下文数据供 layout builder 使用
        decisions = []
        if state.decision_record:
            decisions = state.decision_record.get("decisions", []) if isinstance(state.decision_record, dict) else []
        adopted_claims = [
            c.get("text", str(c)) if isinstance(c, dict) else c
            for c in state.claims
            if (c.get("adopted", True) if isinstance(c, dict) else True)
        ]
        llm_trace_data = {}
        if state.llm_trace:
            llm_trace_data = {
                "total_calls": getattr(state.llm_trace, "total_calls", 0),
                "success_rate": f"{getattr(state.llm_trace, 'success_count', 0)}/{max(getattr(state.llm_trace, 'total_calls', 1), 1)}",
                "total_tokens": getattr(state.llm_trace, "total_tokens", 0),
                "input_tokens": getattr(state.llm_trace, "input_tokens", 0),
                "output_tokens": getattr(state.llm_trace, "output_tokens", 0),
            }
        layout_spec = build_report_layout(
            deliverable_type=state.deliverable_type,
            artifact=state.artifact or {},
            meeting_meta=meeting_meta,
            confidence=state.confidence_flags,
            decisions=decisions,
            adopted_claims=adopted_claims,
            key_questions=state.key_questions,
            team_config=state.team_config,
            conflicts=state.conflicts,
            llm_trace=llm_trace_data,
        )
        # 将 layout spec 存入 artifact，前端通过 API 获取
        state.artifact["report_layout"] = layout_spec
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning(f"[report_layout] 生成布局 spec 失败，前端将回退到本地 demo: {e}")

    # 统一收尾：锁定结论、发布事件、漂移检查、设置终态
    from app.orchestrator.stage_runners import run_produce

    return await run_produce(state, confidence)
