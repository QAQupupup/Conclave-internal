# 配置：LLM provider/key、向量库地址，全部读环境变量，缺省走 stub
from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    # LLM 配置：无 key 时走 StubLLM
    llm_api_key: str = _env("CONCLAVE_LLM_API_KEY", "")
    llm_base_url: str = _env("CONCLAVE_LLM_BASE_URL", "")
    llm_model: str = _env("CONCLAVE_LLM_MODEL", "gpt-4o-mini")

    # 向量库地址：留空走内存向量存储
    qdrant_url: str = _env("CONCLAVE_QDRANT_URL", "")
    qdrant_collection: str = _env("CONCLAVE_QDRANT_COLLECTION", "conclave_chunks")

    # SQLite 数据库路径
    sqlite_path: str = _env("CONCLAVE_DB_PATH", "conclave.db")

    # 嵌入向量维度（StubEmbedding 用）
    embed_dim: int = int(_env("CONCLAVE_EMBED_DIM", "64"))

    @property
    def use_real_llm(self) -> bool:
        """是否启用真实 LLM"""
        return bool(self.llm_api_key)

    @property
    def use_qdrant(self) -> bool:
        """是否启用 Qdrant 向量库"""
        return bool(self.qdrant_url)


settings = Settings()
