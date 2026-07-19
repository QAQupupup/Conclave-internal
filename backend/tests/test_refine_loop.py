# RefineLoop 代码自修复循环测试
# 验证：成功路径、失败修正、重复检测终止、网络授权触发
from unittest.mock import MagicMock

from app.orchestrator.refine_loop import _summarize_task, refine_python_code

# ---------- 成功路径 ----------


async def test_refine_success_first_round():
    """第一轮执行就成功（exit_code=0），应立即返回"""
    call_count = 0

    async def run_fn(code):
        nonlocal call_count
        call_count += 1
        return {"exit_code": 0, "stdout": "count: 3\nsum: 60", "stderr": ""}

    result = await refine_python_code(
        initial_code="print('hello')",
        task_summary="数据分析任务",
        run_fn=run_fn,
        max_rounds=5,
    )

    assert result["success"] is True
    assert result["rounds_used"] == 1
    assert call_count == 1  # 成功后不再重试
    assert result["code"] == "print('hello')"


async def test_refine_success_after_retry():
    """第一轮失败，LLM 修正后第二轮成功"""
    call_count = 0

    async def run_fn(code):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"exit_code": 1, "stdout": "", "stderr": "NameError: name 'data' is not defined"}
        return {"exit_code": 0, "stdout": "count: 3", "stderr": ""}

    # mock LLM 返回修正代码（字段名是 code 不是 fixed_code）
    mock_llm = MagicMock()

    async def mock_complete(prompt, schema_hint=""):
        return {"code": "data = [1,2,3]\nprint(len(data))"}

    mock_llm.complete = mock_complete

    import app.orchestrator.refine_loop as refine_mod

    original_get_llm = refine_mod.get_llm
    refine_mod.get_llm = lambda: mock_llm
    try:
        result = await refine_python_code(
            initial_code="print(len(data))",
            task_summary="数据分析任务",
            run_fn=run_fn,
            max_rounds=5,
        )
    finally:
        refine_mod.get_llm = original_get_llm

    assert result["success"] is True
    assert result["rounds_used"] == 2
    assert call_count == 2


# ---------- 失败 + 重复检测终止 ----------


async def test_refine_no_change_terminate():
    """LLM 返回的代码和上一轮相同，应终止"""
    call_count = 0

    async def run_fn(code):
        nonlocal call_count
        call_count += 1
        return {"exit_code": 1, "stdout": "", "stderr": "SyntaxError: invalid syntax"}

    # mock LLM 返回相同代码（不修正）
    mock_llm = MagicMock()

    async def mock_complete(prompt, schema_hint=""):
        return {"code": "print('hello')"}  # 每次返回相同

    mock_llm.complete = mock_complete

    import app.orchestrator.refine_loop as refine_mod

    original_get_llm = refine_mod.get_llm
    refine_mod.get_llm = lambda: mock_llm
    try:
        result = await refine_python_code(
            initial_code="print('hello')",
            task_summary="任务",
            run_fn=run_fn,
            max_rounds=5,
        )
    finally:
        refine_mod.get_llm = original_get_llm

    assert result["success"] is False
    # 第1轮失败 + LLM修正(代码不变) → 第2轮发现代码未变化 → 终止
    assert result["rounds_used"] <= 3  # 重复检测应在 2-3 轮内终止


# ---------- max_rounds 限制 ----------


async def test_refine_max_rounds():
    """达到 max_rounds 仍未成功，应终止并返回 success=False"""
    call_count = 0

    async def run_fn(code):
        nonlocal call_count
        call_count += 1
        return {"exit_code": 1, "stdout": "", "stderr": "persistent error"}

    # mock LLM 每次返回不同代码（避免重复检测）
    mock_llm = MagicMock()
    fix_counter = 0

    async def mock_complete(prompt, schema_hint=""):
        nonlocal fix_counter
        fix_counter += 1
        return {"code": f"# attempt {fix_counter}\nprint({fix_counter})"}

    mock_llm.complete = mock_complete

    import app.orchestrator.refine_loop as refine_mod

    original_get_llm = refine_mod.get_llm
    refine_mod.get_llm = lambda: mock_llm
    try:
        result = await refine_python_code(
            initial_code="print('init')",
            task_summary="任务",
            run_fn=run_fn,
            max_rounds=3,
        )
    finally:
        refine_mod.get_llm = original_get_llm

    assert result["success"] is False
    assert result["rounds_used"] == 3


# ---------- _summarize_task 辅助函数 ----------


def test_summarize_task_code_analysis():
    """_summarize_task 正确生成 code_analysis 任务摘要"""
    result = {
        "code_analysis": {
            "title": "数据分析",
            "description": "统计订单数据",
            "code": "print('hello')",
        }
    }
    summary = _summarize_task("code_analysis", result)
    assert "数据分析" in summary or "统计" in summary or "code_analysis" in summary


def test_summarize_task_tested_system():
    """_summarize_task 正确生成 tested_system 任务摘要"""
    result = {
        "tested_system": {
            "title": "计算器模块",
            "description": "加法运算测试",
            "main_code": "def add(a,b): return a+b",
            "test_code": "def test_add(): assert add(1,2)==3",
        }
    }
    summary = _summarize_task("tested_system", result)
    assert len(summary) > 0


# ---------- 网络授权触发 ----------


async def test_refine_triggers_net_auth():
    """L1 网络下代码失败（网络错误），应触发网络授权申请"""
    call_count = 0

    async def run_fn(code):
        nonlocal call_count
        call_count += 1
        return {
            "exit_code": 1,
            "stdout": "",
            "stderr": "ModuleNotFoundError: No module named 'requests'",
        }

    # mock LLM 不修正代码
    mock_llm = MagicMock()

    async def mock_complete(prompt, schema_hint=""):
        return {"code": "import requests\nprint(requests)"}

    mock_llm.complete = mock_complete

    # mock 网络授权管理器返回自动通过
    import app.orchestrator.refine_loop as refine_mod

    original_get_llm = refine_mod.get_llm
    refine_mod.get_llm = lambda: mock_llm

    # mock request_network_access 返回 approved
    import app.net_auth_manager as nam_mod

    original_request = nam_mod.request_network_access

    auth_called = False

    async def mock_request(*args, **kwargs):
        nonlocal auth_called
        auth_called = True
        return {"approved": True, "level": "L2", "request_id": "test-auth-001"}

    nam_mod.request_network_access = mock_request

    try:
        result = await refine_python_code(
            initial_code="import requests\nrequests.get('https://example.com')",
            task_summary="需要网络的任务",
            run_fn=run_fn,
            max_rounds=5,
            meeting_id="test-mtg-001",
            stage="produce",
            detected_level="L1",
        )
    finally:
        refine_mod.get_llm = original_get_llm
        nam_mod.request_network_access = original_request

    # 网络授权被调用
    assert auth_called, "应触发网络授权申请"
    # 返回 need_retry_with_level
    assert result.get("need_retry_with_level") == "L2"


async def test_refine_net_auth_denied_continues():
    """网络授权被拒绝后，RefineLoop 应继续修正代码"""
    call_count = 0

    async def run_fn(code):
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            return {"exit_code": 1, "stdout": "", "stderr": "ModuleNotFoundError: No module named 'requests'"}
        # 第二轮改为不依赖网络的代码
        return {"exit_code": 0, "stdout": "ok", "stderr": ""}

    mock_llm = MagicMock()

    async def mock_complete(prompt, schema_hint=""):
        return {"code": "print('no network needed')"}

    mock_llm.complete = mock_complete

    import app.orchestrator.refine_loop as refine_mod

    original_get_llm = refine_mod.get_llm
    refine_mod.get_llm = lambda: mock_llm

    import app.net_auth_manager as nam_mod

    original_request = nam_mod.request_network_access

    async def mock_request(*args, **kwargs):
        return {"approved": False, "level": None, "request_id": "test-denied", "denied": True}

    nam_mod.request_network_access = mock_request

    try:
        result = await refine_python_code(
            initial_code="import requests",
            task_summary="任务",
            run_fn=run_fn,
            max_rounds=5,
            meeting_id="test-mtg-denied",
            stage="produce",
            detected_level="L1",
        )
    finally:
        refine_mod.get_llm = original_get_llm
        nam_mod.request_network_access = original_request

    # 授权被拒绝后继续修正，最终成功
    assert result["success"] is True
    assert result.get("net_auth") is not None
