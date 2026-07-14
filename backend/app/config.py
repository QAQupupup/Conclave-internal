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

    # LLM 确定性参数（全部支持环境变量覆盖，默认值保持向后兼容）
    llm_seed: int = int(_env("CONCLAVE_LLM_SEED", "42"))
    llm_top_p: float = float(_env("CONCLAVE_LLM_TOP_P", "1.0"))
    llm_no_think: bool = _env("CONCLAVE_LLM_NO_THINK", "1") == "1"
    llm_max_prompt_tokens: int = int(_env("CONCLAVE_LLM_MAX_PROMPT_TOKENS", "32000"))
    llm_max_attempts: int = int(_env("CONCLAVE_LLM_MAX_ATTEMPTS", "3"))
    llm_default_timeout: float = float(_env("CONCLAVE_LLM_TIMEOUT", "120.0"))
    llm_produce_timeout: float = float(_env("CONCLAVE_PRODUCE_TIMEOUT", "1200.0"))

    # 熔断器参数
    llm_circuit_failure_threshold: int = int(_env("CONCLAVE_LLM_CIRCUIT_THRESHOLD", "5"))
    llm_circuit_recovery_timeout: float = float(_env("CONCLAVE_LLM_CIRCUIT_RECOVERY", "60.0"))

    # 阶段温度策略（JSON 字符串，支持完整覆盖）
    llm_stage_temperatures: str = _env(
        "CONCLAVE_LLM_STAGE_TEMPERATURES",
        '{"clarify":0.0,"intra_team":0.3,"cross_team":0.0,"evidence_check":0.0,"arbitrate":0.0,"produce":0.1,"produce_prd_openapi":0.1,"produce_design_doc":0.1,"produce_comprehensive":0.1,"produce_research_report":0.1,"produce_business_report":0.1,"produce_code_analysis":0.1,"produce_tested_system":0.1,"produce_deployable_service":0.1}',
    )

    # Embedding 配置：无 key 时走 StubEmbedding
    embed_api_key: str = _env("CONCLAVE_EMBED_API_KEY", "")
    embed_base_url: str = _env("CONCLAVE_EMBED_BASE_URL", "")
    embed_model: str = _env("CONCLAVE_EMBED_MODEL", "BAAI/bge-m3")

    # Reranker 配置：无 key 时走关键词加成重排
    rerank_api_key: str = _env("CONCLAVE_RERANK_API_KEY", "")
    rerank_base_url: str = _env("CONCLAVE_RERANK_BASE_URL", "")
    rerank_model: str = _env("CONCLAVE_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")

    # Qdrant 向量库 URL（为空时用内存伪向量）
    # Docker 内用容器名访问，本机开发用 localhost
    # [CON-18 修复] 旧版在 L50 和 L78 重复定义 qdrant_url 字段，
    # Python @dataclass(frozen=True) 实际上保留最后一个定义，
    # 行为无歧义但严重违反代码规范。本次合并为单一定义。
    # 默认值为空（与 use_qdrant property 配合：空值 → 用内存伪向量）
    qdrant_url: str = _env("CONCLAVE_QDRANT_URL", "")
    qdrant_collection: str = _env("CONCLAVE_QDRANT_COLLECTION", "conclave_chunks")

    # PostgreSQL 连接 URL（SQLAlchemy async）
    # 格式: postgresql+asyncpg://user:pass@host:5432/db
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://conclave:conclave_dev@localhost:5432/conclave",
    )

    # Redis 连接 URL
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # 数据目录路径（用于存放密钥文件等本地数据，非数据库路径）
    db_path: str = _env("CONCLAVE_DB_PATH", str(Path.home() / ".conclave" / "data" / "conclave.db"))

    # StubEmbedding 伪向量维度（仅 stub 模式用）
    embed_dim: int = int(_env("CONCLAVE_EMBED_DIM", "64"))

    # [CON-18 修复] 删除了行 78 的 qdrant_url 重复字段定义。
    # 单一来源：见 L50 附近。

    # 会议工作区根目录
    # [CON-24 修复] 旧版用 tempfile.mkdtemp() 创建会议工作区，进程崩溃后无法清理。
    # 改为：默认 <conclave_root>/workspace/meetings/，每次启动清理孤立临时目录。
    workspace_root: str = _env(
        "CONCLAVE_WORKSPACE_DIR",
        str(Path.home() / ".conclave" / "workspace"),
    )

    # 三层记忆开关：CONCLAVE_MEMORY_DISABLED 环境变量存在（非空）时禁用
    memory_enabled: bool = _env("CONCLAVE_MEMORY_DISABLED", "") == ""

    # Agent 计算解耦：CONCLAVE_GRPC_COMPUTE=1 时启用远程 gRPC Worker，否则走本地进程内计算
    use_grpc_compute: bool = _env("CONCLAVE_GRPC_COMPUTE", "") == "1"
    # gRPC Worker 端点地址
    grpc_compute_endpoint: str = _env("CONCLAVE_GRPC_ENDPOINT", "localhost:50051")

    # Web Search 配置
    # 模式：stub(默认空结果) | tavily(API) | playwright(自建无头浏览器)
    web_search_mode: str = _env("CONCLAVE_WEB_SEARCH_MODE", "playwright")
    # Tavily API key（仅 tavily 模式需要）
    web_search_api_key: str = _env("CONCLAVE_WEB_SEARCH_API_KEY", "")

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

    @property
    def db_mode(self) -> str:
        """从 database_url 推断数据库模式：postgresql 或 sqlite"""
        if self.database_url.startswith("postgresql"):
            return "postgresql"
        return "sqlite"


settings = Settings()
