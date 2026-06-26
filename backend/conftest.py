# 测试全局配置：必须在导入 app 之前设置环境变量
import os
import tempfile

# 测试强制走 stub 模式，不调真实 API
os.environ.setdefault("CONCLAVE_LLM_API_KEY", "")
os.environ.setdefault("CONCLAVE_EMBED_API_KEY", "")
os.environ.setdefault("CONCLAVE_RERANK_API_KEY", "")

# SQLite 路径指向临时目录，避免污染工作目录
os.environ.setdefault(
    "CONCLAVE_DB_PATH", os.path.join(tempfile.gettempdir(), "conclave_test.db")
)

# 迭代二：测试时禁用记忆提取，避免历史画像干扰断言
os.environ.setdefault("CONCLAVE_MEMORY_DISABLED", "1")
