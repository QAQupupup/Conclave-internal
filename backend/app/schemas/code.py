# 代码检索相关 DTO（ADR-016 Phase C）
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

MAX_QUERY_LEN = 1024
MAX_NODE_ID_LEN = 512


def _strip_or_raise(value: str, field_name: str) -> str:
    """去首尾空白后校验非空，防止纯空白输入（如 ``"   "``）绕过 min_length 校验。"""
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name}不能为空")
    return stripped


class CodeRetrieveRequest(BaseModel):
    """代码检索请求：向量入口 + N 跳图扩展（retrieve_code）。"""

    query: str = Field(..., min_length=1, max_length=MAX_QUERY_LEN, description="检索查询")
    top_k: int = Field(default=5, ge=1, le=50, description="返回条数")
    max_hops: int = Field(default=1, ge=0, le=5, description="图扩展最大跳数")

    @field_validator("query")
    @classmethod
    def _validate_query(cls, v: str) -> str:
        return _strip_or_raise(v, "检索查询")


class StructureQueryRequest(BaseModel):
    """代码结构查询请求：谁调用它 / 它依赖谁（structure_query）。"""

    node_id: str = Field(
        ..., min_length=1, max_length=MAX_NODE_ID_LEN, description="符号/文件节点 ID（限定名，如 a.py::A::m）"
    )
    max_hops: int = Field(default=1, ge=0, le=5, description="图扩展最大跳数")

    @field_validator("node_id")
    @classmethod
    def _validate_node_id(cls, v: str) -> str:
        return _strip_or_raise(v, "节点 ID")
