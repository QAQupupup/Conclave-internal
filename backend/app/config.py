# 配置：LLM / Embedding / Reranker，全部读环境变量，缺省走 stub
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    """轻量 .env 加载器：从项目根目录读取，不覆盖已有环境变量"""
    # 向上查找 .env（backend/app/ → backend/ → 项目根）
    for p in Path(__file__).resolve().parents:
        env_file = p / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip("'\"")
                os.environ.setdefault(key, val)
            break


_load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    # LLM 配置：无 key 时走 StubLLM
    llm_api_key: str = _env("CONCLAVE_LLM_API_KEY", "")
    llm_base_url: str = _env("CONCLAVE_LLM_BASE_URL", "")
    llm_model: str = _env("CONCLAVE_LLM_MODEL", "Qwen/Qwen3.5-4B")

    # Embedding 配置：无 key 时走 StubEmbedding
    embed_api_key: str = _env("CONCLAVE_EMBED_API_KEY", "")
    embed_base_url: str = _env("CONCLAVE_EMBED_BASE_URL", "")
    embed_model: str = _env("CONCLAVE_EMBED_MODEL", "BAAI/bge-m3")

    # Reranker 配置：无 key 时走关键词加成重排
    rerank_api_key: str = _env("CONCLAVE_RERANK_API_KEY", "")
    rerank_base_url: str = _env("CONCLAVE_RERANK_BASE_URL", "")
    rerank_model: str = _env("CONCLAVE_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")

    # 向量库地址：留空走内存向量存储
    qdrant_url: str = _env("CONCLAVE_QDRANT_URL", "")
    qdrant_collection: str = _env("CONCLAVE_QDRANT_COLLECTION", "conclave_chunks")

    # SQLite 数据库路径
    sqlite_path: str = _env("CONCLAVE_DB_PATH", "conclave.db")

    # StubEmbedding 伪向量维度（仅 stub 模式用）
    embed_dim: int = int(_env("CONCLAVE_EMBED_DIM", "64"))

    # 三层记忆开关：CONCLAVE_MEMORY_DISABLED 环境变量存在（非空）时禁用
    memory_enabled: bool = _env("CONCLAVE_MEMORY_DISABLED", "") == ""

    @property
    def use_real_llm(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def use_real_embed(self) -> bool:
        return bool(self.embed_api_key)

    @property
    def use_real_rerank(self) -> bool:
        return bool(self.rerank_api_key)

    @property
    def use_qdrant(self) -> bool:
        return bool(self.qdrant_url)


settings = Settings()
