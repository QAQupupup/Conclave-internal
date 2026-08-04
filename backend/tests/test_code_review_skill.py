"""代码审查 Skill 单元测试。

验证 code_review.yaml skill 正确加载、security_expert 角色在 produce 阶段匹配、
双层安全审查架构（进程内 regex 扫描 + LLM 深度审查）正确集成。
"""

import inspect

import pytest

from app.agents.skills import get_active_skills, load_all_skills


class TestCodeReviewSkillLoad:
    """验证 skill 正确加载。"""

    def test_code_review_exists(self):
        """load_all_skills() 返回包含 id=code_review 的 skill。"""
        skills = load_all_skills()
        ids = [s.id for s in skills]
        assert "code_review" in ids, f"code_review 未加载，已加载: {ids}"

    def test_priority_is_80(self):
        """priority 必须为 80。"""
        skills = {s.id: s for s in load_all_skills()}
        assert skills["code_review"].priority == 80

    def test_type_is_constraint(self):
        """type 必须为 constraint。"""
        skills = {s.id: s for s in load_all_skills()}
        assert skills["code_review"].type == "constraint"

    def test_version_is_2(self):
        """v2.0 双层审查架构。"""
        skills = {s.id: s for s in load_all_skills()}
        assert skills["code_review"].version.startswith("2")


class TestCodeReviewMatching:
    """验证 applies_to 匹配规则正确。"""

    def test_matches_security_expert_backend_service(self):
        """produce+backend_service+security_expert 时匹配。"""
        active = get_active_skills(stage="produce", deliverable_type="backend_service", role="security_expert")
        ids = [s.id for s in active]
        assert "code_review" in ids

    def test_matches_security_expert_frontend_app(self):
        """produce+frontend_app+security_expert 时匹配。"""
        active = get_active_skills(stage="produce", deliverable_type="frontend_app", role="security_expert")
        ids = [s.id for s in active]
        assert "code_review" in ids

    def test_matches_security_expert_tested_system(self):
        """produce+tested_system+security_expert 时匹配。"""
        active = get_active_skills(stage="produce", deliverable_type="tested_system", role="security_expert")
        ids = [s.id for s in active]
        assert "code_review" in ids

    def test_matches_security_expert_code_analysis(self):
        """produce+code_analysis+security_expert 时匹配。"""
        active = get_active_skills(stage="produce", deliverable_type="code_analysis", role="security_expert")
        ids = [s.id for s in active]
        assert "code_review" in ids

    def test_not_match_engineer_role(self):
        """role=engineer 时不匹配（仅 security_expert）。"""
        active = get_active_skills(stage="produce", deliverable_type="backend_service", role="engineer")
        ids = [s.id for s in active]
        assert "code_review" not in ids

    def test_not_match_non_produce_stage(self):
        """stage=review 时不匹配（仅 produce）。"""
        active = get_active_skills(stage="review", deliverable_type="backend_service", role="security_expert")
        ids = [s.id for s in active]
        assert "code_review" not in ids

    def test_not_match_prd_type(self):
        """deliverable_type=prd_openapi 时不匹配。"""
        active = get_active_skills(stage="produce", deliverable_type="prd_openapi", role="security_expert")
        ids = [s.id for s in active]
        assert "code_review" not in ids


class TestCodeReviewPromptContent:
    """验证 prompt 包含关键章节。"""

    def test_prompt_contains_vulnerability_levels(self):
        """prompt 包含四级漏洞分级。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["code_review"].prompt
        for level in ["critical", "high", "medium", "low"]:
            assert level in prompt, f"prompt 缺少漏洞等级 {level}"

    def test_prompt_contains_block_deploy_rule(self):
        """prompt 包含 critical 阻断部署规则。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["code_review"].prompt
        assert "阻断部署" in prompt or "BLOCK" in prompt

    def test_prompt_contains_sql_injection(self):
        """prompt 包含 SQL 注入作为 critical 示例。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["code_review"].prompt
        assert "SQL 注入" in prompt or "sql-injection" in prompt

    def test_prompt_contains_python_rules(self):
        """prompt 包含 Python/FastAPI 审查清单。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["code_review"].prompt
        assert "Python" in prompt and "FastAPI" in prompt

    def test_prompt_contains_typescript_rules(self):
        """prompt 包含 TypeScript/React 审查清单。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["code_review"].prompt
        assert "TypeScript" in prompt or "React" in prompt

    def test_prompt_contains_go_rules(self):
        """prompt 包含 Go 审查清单。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["code_review"].prompt
        assert "Go" in prompt or "goroutine" in prompt

    def test_prompt_contains_cpp_rules(self):
        """prompt 包含 C/C++ 审查清单。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["code_review"].prompt
        assert "C/C++" in prompt or "缓冲区溢出" in prompt

    def test_prompt_contains_two_layer_architecture(self):
        """prompt 说明双层审查架构。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["code_review"].prompt
        assert "双层" in prompt or "两层" in prompt
        assert "regex" in prompt or "确定性" in prompt
        assert "LLM" in prompt or "深度审查" in prompt

    def test_prompt_contains_output_format(self):
        """prompt 包含输出格式要求。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["code_review"].prompt
        assert "安全审查报告" in prompt
        assert "PASS" in prompt or "通过" in prompt

    def test_prompt_no_external_dependency(self):
        """v2.0 prompt 不依赖外部工具/API。"""
        skills = {s.id: s for s in load_all_skills()}
        prompt = skills["code_review"].prompt
        assert "不调用外部 API" in prompt or "不出网" in prompt


class TestInprocessSecurityScan:
    """验证进程内静态安全扫描函数。"""

    def test_scan_function_exists_in_produce(self):
        """produce 模块导出 _run_inprocess_security_scan 异步函数。"""
        from app.orchestrator.nodes import produce

        assert hasattr(produce, "_run_inprocess_security_scan")
        assert inspect.iscoroutinefunction(produce._run_inprocess_security_scan)

    def test_scan_function_signature(self):
        """_run_inprocess_security_scan 接受 meeting_id 和 code_dir 参数。"""
        from app.orchestrator.nodes import produce

        sig = inspect.signature(produce._run_inprocess_security_scan)
        params = list(sig.parameters.keys())
        assert "meeting_id" in params
        assert "code_dir" in params

    def test_scan_critical_patterns_defined(self):
        """produce 模块定义了 critical 级扫描规则。"""
        from app.orchestrator.nodes import produce

        assert hasattr(produce, "_CRITICAL_PATTERNS")
        rule_ids = [p[2] for p in produce._CRITICAL_PATTERNS]
        assert any("cmd-injection" in r for r in rule_ids)
        assert any("sql-injection" in r for r in rule_ids)
        assert any("hardcoded-secret" in r for r in rule_ids)
        assert any("pickle" in r for r in rule_ids)
        assert any("eval" in r or "exec" in r for r in rule_ids)

    def test_scan_high_patterns_defined(self):
        """produce 模块定义了 high 级扫描规则。"""
        from app.orchestrator.nodes import produce

        assert hasattr(produce, "_HIGH_PATTERNS")
        rule_ids = [p[2] for p in produce._HIGH_PATTERNS]
        assert any("yaml" in r for r in rule_ids)
        assert any("ssl" in r for r in rule_ids)
        assert any("debug" in r for r in rule_ids)
        assert any("except" in r for r in rule_ids)

    def test_code_exts_cover_major_languages(self):
        """扫描扩展名覆盖 Python/TS/JS/Go/C/C++/Java/Rust。"""
        from app.orchestrator.nodes import produce

        exts = produce._CODE_EXTS
        assert ".py" in exts
        assert ".ts" in exts
        assert ".js" in exts
        assert ".go" in exts
        assert ".c" in exts
        assert ".cpp" in exts
        assert ".java" in exts
        assert ".rs" in exts

    @pytest.mark.asyncio
    async def test_scan_detects_sql_injection(self, tmp_path):
        """扫描能检测到 f-string SQL 注入。"""
        from app.orchestrator.nodes import produce

        code_file = tmp_path / "app.py"
        code_file.write_text(
            "import sqlite3\n"
            "def get_user(user_id):\n"
            '    conn = sqlite3.connect("db")\n'
            '    return conn.execute(f"SELECT * FROM users WHERE id = {user_id}")\n'
        )
        result = await produce._run_inprocess_security_scan(meeting_id="test-mt", code_dir=tmp_path)
        assert result["ok"] is True
        assert result["critical"] >= 1
        assert result["block_deploy"] is True
        issue_rules = [i["rule"] for i in result["issues"]]
        assert any("sql-injection" in r for r in issue_rules)

    @pytest.mark.asyncio
    async def test_scan_detects_hardcoded_secret(self, tmp_path):
        """扫描能检测到硬编码密钥。"""
        from app.orchestrator.nodes import produce

        code_file = tmp_path / "config.py"
        code_file.write_text('api_key = "sk-1234567890abcdefghijklmnop"\n')
        result = await produce._run_inprocess_security_scan(meeting_id="test-mt", code_dir=tmp_path)
        assert result["critical"] >= 1
        assert any("hardcoded-secret" in i["rule"] for i in result["issues"])

    @pytest.mark.asyncio
    async def test_scan_detects_pickle(self, tmp_path):
        """扫描能检测到 pickle.loads。"""
        from app.orchestrator.nodes import produce

        code_file = tmp_path / "load.py"
        code_file.write_text("import pickle\ndata = pickle.loads(user_input)\n")
        result = await produce._run_inprocess_security_scan(meeting_id="test-mt", code_dir=tmp_path)
        assert result["critical"] >= 1
        assert any("pickle" in i["rule"] for i in result["issues"])

    @pytest.mark.asyncio
    async def test_scan_detects_shell_true(self, tmp_path):
        """扫描能检测到 subprocess shell=True。"""
        from app.orchestrator.nodes import produce

        code_file = tmp_path / "run.py"
        code_file.write_text("import subprocess\nsubprocess.run(user_cmd, shell=True)\n")
        result = await produce._run_inprocess_security_scan(meeting_id="test-mt", code_dir=tmp_path)
        assert result["critical"] >= 1
        assert any("cmd-injection" in i["rule"] for i in result["issues"])

    @pytest.mark.asyncio
    async def test_scan_clean_code_passes(self, tmp_path):
        """干净代码不触发 critical 问题。"""
        from app.orchestrator.nodes import produce

        code_file = tmp_path / "app.py"
        code_file.write_text(
            "import os\n"
            "from typing import Optional\n"
            "\n"
            "def greet(name: str) -> str:\n"
            '    """Return a greeting message."""\n'
            '    return f"Hello, {name}"\n'
            "\n"
            "async def fetch_data(url: str) -> Optional[dict]:\n"
            '    """Fetch data from URL using httpx."""\n'
            "    import httpx\n"
            "    async with httpx.AsyncClient() as client:\n"
            "        resp = await client.get(url, timeout=10)\n"
            "        resp.raise_for_status()\n"
            "        return resp.json()\n"
        )
        result = await produce._run_inprocess_security_scan(meeting_id="test-mt", code_dir=tmp_path)
        assert result["critical"] == 0
        assert result["block_deploy"] is False
        assert result["files_scanned"] == 1

    @pytest.mark.asyncio
    async def test_scan_skips_venv_and_pycache(self, tmp_path):
        """扫描跳过 .venv、__pycache__、node_modules 等目录。"""
        from app.orchestrator.nodes import produce

        (tmp_path / "app.py").write_text("print('hello')\n")

        venv_dir = tmp_path / ".venv" / "lib"
        venv_dir.mkdir(parents=True)
        (venv_dir / "bad.py").write_text('api_key = "sk-abcdefghijklmnopqrstuvwxyz1234567890"\n')

        pycache_dir = tmp_path / "__pycache__"
        pycache_dir.mkdir()
        (pycache_dir / "bad.py").write_text("import pickle\ndata = pickle.loads(x)\n")

        result = await produce._run_inprocess_security_scan(meeting_id="test-mt", code_dir=tmp_path)
        assert result["files_scanned"] == 1
        assert result["critical"] == 0

    @pytest.mark.asyncio
    async def test_scan_nonexistent_dir(self, tmp_path):
        """工作目录不存在时返回 ok 但无问题。"""
        from app.orchestrator.nodes import produce

        result = await produce._run_inprocess_security_scan(meeting_id="test-mt", code_dir=tmp_path / "nonexistent")
        assert result["ok"] is True
        assert result["critical"] == 0
        assert result["files_scanned"] == 0
