# 单用例执行器：创建会议 -> 运行 -> 轮询等待完成 -> 获取详情 -> 各阶段评分
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from eval.graders.base import GraderResult
from eval.graders.exact_match import ExactMatchGrader
from eval.graders.field_check import FieldCheckGrader
from eval.graders.llm_judge import LLMJudgeGrader
from eval.models import CaseResult

POLL_INTERVAL = 3.0
DEFAULT_TIMEOUT = 300.0
PASS_THRESHOLD = 0.6

# 会议终态：进入这些状态后不再变化
_TERMINAL_STATUSES = {"done", "failed", "aborted"}


class CaseRunner:
    """单用例执行器。

    通过 Conclave 会议 API 运行一个测试用例：创建会议、触发运行、轮询直到完成、
    获取会议详情，然后按用例 ``expected`` 中各阶段的判定标准进行评分。
    """

    def __init__(self, base_url: str, auth_token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self.headers: dict[str, str] = {"Content-Type": "application/json"}
        if auth_token:
            self.headers["Authorization"] = f"Bearer {auth_token}"
        self._exact = ExactMatchGrader()
        self._field = FieldCheckGrader()
        self._judge: LLMJudgeGrader | None = None
        self._stage_handlers: dict[str, Any] = {
            "clarify": self._grade_clarify,
            "intra_team": self._grade_intra_team,
            "cross_team": self._grade_cross_team,
            "evidence_check": self._grade_evidence_check,
            "arbitrate": self._grade_arbitrate,
            "produce": self._grade_produce,
        }

    def set_judge(self, judge: LLMJudgeGrader) -> None:
        """注入 LLM-as-Judge 评分器（用于 produce 等需要语义评分的阶段）。"""
        self._judge = judge

    async def run_case(self, case: dict) -> CaseResult:
        case_id = case.get("case_id", "unknown")
        tier = case.get("tier", 0)
        errors: list[str] = []
        stage_scores: dict[str, float] = {}
        start = time.monotonic()
        total_tokens = 0
        meeting_id = ""
        audit_data: dict[str, Any] = {}

        try:
            meeting_id = await self._create_meeting(case)
            await self._upload_docs(meeting_id, case)
            await self._start_meeting(meeting_id)
            detail = await self._wait_and_fetch(meeting_id, case)
            total_tokens = self._extract_tokens(detail)
            stage_scores = await self._grade_all_stages(case, detail)
            self._check_terminal_state(case, detail, errors)
            # 获取完整审计数据（best-effort，失败不影响评分）
            if not errors:
                audit_data = await self._fetch_audit(meeting_id)
        except TimeoutError:
            errors.append("case timed out waiting for meeting to finish")
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            body = exc.response.text[:200] if exc.response is not None else ""
            errors.append(f"http {code}: {body}")
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")

        latency = (time.monotonic() - start) * 1000.0
        passed = not errors and bool(stage_scores) and all(v >= PASS_THRESHOLD for v in stage_scores.values())
        return CaseResult(
            case_id=case_id,
            tier=tier,
            passed=passed,
            stage_scores=stage_scores,
            total_tokens=total_tokens,
            latency_ms=latency,
            errors=errors,
            run_index=int(case.get("run_index", 0)),
            meeting_id=meeting_id,
            audit_data=audit_data,
        )

    # ---------- HTTP 流程 ----------

    async def _create_meeting(self, case: dict) -> str:
        params = self._build_meeting_params(case)
        async with httpx.AsyncClient(timeout=30.0, headers=self.headers, trust_env=False) as client:
            resp = await client.post(f"{self.base_url}/meetings", json=params)
            resp.raise_for_status()
            return resp.json()["meeting_id"]

    async def _start_meeting(self, meeting_id: str) -> None:
        async with httpx.AsyncClient(timeout=30.0, headers=self.headers, trust_env=False) as client:
            resp = await client.post(f"{self.base_url}/meetings/{meeting_id}/run")
            resp.raise_for_status()

    async def _upload_docs(self, meeting_id: str, case: dict) -> None:
        """上传测试用例中的文档（multipart form data）。

        在会议创建后、启动前调用，模拟用户上传参考资料的场景。
        """
        docs = case.get("uploaded_docs") or []
        if not docs:
            return
        upload_headers = dict(self.headers)
        upload_headers.pop("Content-Type", None)
        async with httpx.AsyncClient(timeout=30.0, headers=upload_headers, trust_env=False) as client:
            for doc in docs:
                filename = doc.get("filename", "doc.md")
                content = doc.get("content", "")
                files = {"file": (filename, content.encode("utf-8"), "text/markdown")}
                resp = await client.post(
                    f"{self.base_url}/meetings/{meeting_id}/documents",
                    files=files,
                )
                resp.raise_for_status()

    async def _wait_and_fetch(self, meeting_id: str, case: dict) -> dict:
        timeout = float(case.get("timeout", DEFAULT_TIMEOUT))
        deadline = time.monotonic() + timeout
        last_status = ""
        while True:
            async with httpx.AsyncClient(timeout=30.0, headers=self.headers, trust_env=False) as client:
                resp = await client.get(f"{self.base_url}/meetings/{meeting_id}/progress")
                resp.raise_for_status()
                prog = resp.json()
            last_status = prog.get("status", "")
            if last_status in _TERMINAL_STATUSES:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"meeting {meeting_id} did not finish within {timeout}s (last status: {last_status})"
                )
            await asyncio.sleep(POLL_INTERVAL)
        async with httpx.AsyncClient(timeout=30.0, headers=self.headers, trust_env=False) as client:
            resp = await client.get(f"{self.base_url}/meetings/{meeting_id}")
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def _build_meeting_params(case: dict) -> dict:
        cfg = case.get("config") or {}
        params: dict[str, Any] = {
            "topic": case.get("topic", ""),
            "deliverable_type": cfg.get("deliverable_type", "prd_openapi"),
            "flow_plan": cfg.get("flow_plan", "standard"),
            "debate_depth": cfg.get("debate_depth", "standard"),
        }
        # 可选字段透传（仅当 config 中显式提供时）
        for key in (
            "role_ids",
            "reference_meeting_ids",
            "model",
            "auto_iterate",
            "max_iterations",
            "max_stage_retries",
        ):
            if key in cfg:
                params[key] = cfg[key]
        return params

    @staticmethod
    def _extract_tokens(detail: dict) -> int:
        trace = detail.get("llm_trace") or {}
        try:
            return int(trace.get("total_tokens", 0))
        except (TypeError, ValueError):
            return 0

    async def _fetch_audit(self, meeting_id: str) -> dict[str, Any]:
        """获取会议完整审计数据（best-effort，失败返回空 dict）。

        调用 GET /meetings/{id}/audit 端点，获取 trace、events、cost_records、
        质量门禁详情等完整数据，用于 Vault 导出和历史对比。
        """
        try:
            async with httpx.AsyncClient(timeout=30.0, headers=self.headers, trust_env=False) as client:
                resp = await client.get(f"{self.base_url}/meetings/{meeting_id}/audit")
                resp.raise_for_status()
                return resp.json()
        except Exception:
            return {}

    def _check_terminal_state(self, case: dict, detail: dict, errors: list[str]) -> None:
        terminal = case.get("terminal_state") or {}
        expected_status = terminal.get("status")
        expected_stage = terminal.get("stage")
        if expected_status and detail.get("status") != expected_status:
            errors.append(f"terminal status mismatch: expected {expected_status}, got {detail.get('status')}")
        if expected_stage and detail.get("stage") != expected_stage:
            errors.append(f"terminal stage mismatch: expected {expected_stage}, got {detail.get('stage')}")

    # ---------- 阶段评分 ----------

    async def _grade_all_stages(self, case: dict, detail: dict) -> dict[str, float]:
        expected = case.get("expected") or {}
        scores: dict[str, float] = {}
        for stage, criteria in expected.items():
            if not isinstance(criteria, dict):
                continue
            result = await self._grade_stage(stage, criteria, detail)
            scores[stage] = result.score
        return scores

    async def _grade_stage(self, stage: str, criteria: dict, detail: dict) -> GraderResult:
        handler = self._stage_handlers.get(stage)
        if handler is None:
            return GraderResult(score=1.0, passed=True, detail=f"no grader for stage '{stage}'")
        checks: list[tuple[str, bool]] = []
        await handler(criteria, detail, checks)
        if not checks:
            return GraderResult(score=1.0, passed=True, detail=f"no criteria for stage '{stage}'")
        passed_count = sum(1 for _, ok in checks if ok)
        score = passed_count / len(checks)
        failed = [name for name, ok in checks if not ok]
        detail_str = f"{passed_count}/{len(checks)} passed"
        if failed:
            detail_str += f"; failed: {', '.join(failed)}"
        return GraderResult(score=score, passed=passed_count == len(checks), detail=detail_str)

    async def _grade_clarify(self, criteria: dict, detail: dict, checks: list[tuple[str, bool]]) -> None:
        key_questions = detail.get("key_questions") or []
        min_kq = criteria.get("min_key_questions")
        if min_kq is not None:
            checks.append(("min_key_questions", len(key_questions) >= min_kq))
        expected_roles = criteria.get("expected_roles")
        if expected_roles:
            actual_roles = [tc.get("role") for tc in (detail.get("team_config") or [])]
            res = self._exact.grade(expected_roles, actual_roles)
            checks.append(("expected_roles", res.passed))
        # clarified_topic 非空作为 clarify 阶段完成的信号
        checks.append(("clarified_topic_non_empty", bool(detail.get("clarified_topic"))))

    async def _grade_intra_team(self, criteria: dict, detail: dict, checks: list[tuple[str, bool]]) -> None:
        claims = detail.get("claims") or []
        min_claims = criteria.get("min_claims")
        if min_claims is not None:
            checks.append(("min_claims", len(claims) >= min_claims))
        expected_types = criteria.get("expected_claim_types")
        if expected_types:
            actual_types: list[str] = []
            for c in claims:
                t = c.get("type")
                if t:
                    actual_types.append(t)
            res = self._exact.grade(expected_types, actual_types)
            checks.append(("expected_claim_types", res.passed))

    async def _grade_cross_team(self, criteria: dict, detail: dict, checks: list[tuple[str, bool]]) -> None:
        conflicts = detail.get("conflicts") or []
        min_c = criteria.get("min_conflicts")
        max_c = criteria.get("max_conflicts")
        if min_c is not None:
            checks.append(("min_conflicts", len(conflicts) >= min_c))
        if max_c is not None:
            checks.append(("max_conflicts", len(conflicts) <= max_c))
        expected_types = criteria.get("expected_conflict_types")
        if expected_types:
            actual_types = [c.get("type") for c in conflicts if c.get("type")]
            res = self._exact.grade(expected_types, actual_types)
            checks.append(("expected_conflict_types", res.passed))

    async def _grade_evidence_check(self, criteria: dict, detail: dict, checks: list[tuple[str, bool]]) -> None:
        evidence_set = detail.get("evidence_set") or []
        total_assessments = sum(len(es.get("assessments") or []) for es in evidence_set)
        min_assessments = criteria.get("min_evidence_assessments")
        if min_assessments is not None:
            checks.append(("min_evidence_assessments", total_assessments >= min_assessments))
        if "expect_confidence_degradation" in criteria:
            expect_deg = bool(criteria.get("expect_confidence_degradation"))
            flags = detail.get("confidence_flags") or {}
            has_low = any(v == "low" for v in flags.values())
            if expect_deg:
                checks.append(("confidence_degradation_present", has_low))
            else:
                checks.append(("no_confidence_degradation", not has_low))

    async def _grade_arbitrate(self, criteria: dict, detail: dict, checks: list[tuple[str, bool]]) -> None:
        conflicts = detail.get("conflicts") or []
        decision_record = detail.get("decision_record") or {}
        decisions = decision_record.get("decisions") or []
        if criteria.get("all_conflicts_resolved"):
            checks.append(("all_conflicts_resolved", len(decisions) >= len(conflicts)))
        min_decisions = criteria.get("min_decisions")
        if min_decisions is not None:
            checks.append(("min_decisions", len(decisions) >= min_decisions))
        min_rationale = criteria.get("min_rationale_length")
        if min_rationale is not None and decisions:
            ok = all(len(d.get("rationale") or "") >= min_rationale for d in decisions)
            checks.append(("min_rationale_length", ok))

    async def _grade_produce(self, criteria: dict, detail: dict, checks: list[tuple[str, bool]]) -> None:
        artifact = detail.get("artifact") or {}
        deliverable_type = detail.get("deliverable_type") or (detail.get("config") or {}).get(
            "deliverable_type", "prd_openapi"
        )

        # 按产出类型分派检查逻辑
        if deliverable_type in ("design_doc", "comprehensive", "research_report", "business_report"):
            doc = artifact.get(deliverable_type) if isinstance(artifact.get(deliverable_type), dict) else {}
            must_have = criteria.get("must_have_doc_fields")
            if must_have:
                res = self._field.grade(doc, must_have)
                checks.append(("must_have_doc_fields", res.passed))
            min_len = criteria.get("min_doc_length")
            if min_len is not None:
                doc_text = str(doc)
                checks.append(("min_doc_length", len(doc_text) >= min_len))
        else:
            # prd_openapi 及其他类型：保持原有 PRD 字段检查
            prd = artifact.get("prd") if isinstance(artifact.get("prd"), dict) else {}
            must_have = criteria.get("must_have_prd_fields")
            if must_have:
                res = self._field.grade(prd, must_have)
                checks.append(("must_have_prd_fields", res.passed))
            min_api = criteria.get("min_api_endpoints")
            if min_api is not None:
                endpoints = prd.get("api_endpoints") or []
                checks.append(("min_api_endpoints", len(endpoints) >= min_api))
            min_openapi = criteria.get("min_openapi_length")
            if min_openapi is not None:
                openapi = artifact.get("openapi") or ""
                checks.append(("min_openapi_length", len(str(openapi)) >= min_openapi))

        # 可选：LLM-as-Judge 整体质量评分（仅当用例显式请求且 judge 已配置时）
        if criteria.get("use_judge") and self._judge is not None:
            topic = detail.get("topic", "")
            # 根据产出类型选择待评估内容
            if deliverable_type in ("design_doc", "comprehensive", "research_report", "business_report"):
                actual = str(artifact.get(deliverable_type, ""))
            else:
                actual = str(artifact.get("prd", "")) if artifact.get("prd") else str(artifact)
            expected_text = criteria.get(
                "judge_expected", "complete and coherent deliverable with clear structure and actionable content"
            )
            dimension = criteria.get("judge_dimension", "completeness")
            res = await self._judge.grade(topic, expected_text, actual, dimension)
            checks.append(("llm_judge_quality", res.score >= PASS_THRESHOLD))
