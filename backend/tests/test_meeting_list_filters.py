"""会议列表筛选测试（GET /meetings 的 status 参数）

覆盖场景：
1. status 单值过滤：命中的会议在结果中（正向）
2. status 单值过滤：不命中的状态查不到新建会议（非正向）
3. status 多值逗号分隔：OR 语义命中（边界）
4. status 未知值：返回空列表而非报错（异常路径防御）
5. status 与 q 组合过滤：两个条件同时生效（组合）

背景：前端 useMeetings hook 一直在发送 status 参数，但后端此前未声明该参数，
FastAPI 静默忽略导致筛选无效——本组测试锁定参数契约。
"""


def _create_meeting(client, topic: str) -> str:
    resp = client.post("/meetings", json={"topic": topic})
    assert resp.status_code == 200, resp.text
    return resp.json()["meeting_id"]


def _list_ids(client, query: str) -> list[str]:
    resp = client.get(f"/meetings?{query}")
    assert resp.status_code == 200, resp.text
    return [m["meeting_id"] for m in resp.json()["meetings"]]


def test_status_filter_single_value_hits(client):
    """status=running 能查到创建后处于 running 的会议"""
    mid = _create_meeting(client, "状态筛选-单值命中")
    ids = _list_ids(client, "status=running")
    assert mid in ids


def test_status_filter_excludes_non_matching(client):
    """status=done 不应包含刚创建（running）的会议（非正向）"""
    mid = _create_meeting(client, "状态筛选-非匹配排除")
    ids = _list_ids(client, "status=done")
    assert mid not in ids


def test_status_filter_multi_value_or_semantics(client):
    """逗号分隔多状态为 OR 语义：done,running 应命中 running 会议"""
    mid = _create_meeting(client, "状态筛选-多值OR")
    ids = _list_ids(client, "status=done,running")
    assert mid in ids


def test_status_filter_unknown_value_returns_empty(client):
    """未知状态值返回空列表而非 500（异常路径防御）"""
    resp = client.get("/meetings?status=no_such_status")
    assert resp.status_code == 200
    assert resp.json()["meetings"] == []
    assert resp.json()["total"] == 0


def test_status_filter_combined_with_keyword(client):
    """status 与 q 组合：两个条件同时生效"""
    mid_hit = _create_meeting(client, "组合过滤-量子加密通信专题")
    mid_miss = _create_meeting(client, "组合过滤-完全不同的议题")
    ids = _list_ids(client, "status=running&q=量子加密")
    assert mid_hit in ids
    assert mid_miss not in ids
