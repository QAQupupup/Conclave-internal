# 测试全局配置：必须在导入 app 之前设置环境变量
import os
import tempfile

# SQLite 路径指向临时目录，避免污染工作目录
os.environ.setdefault(
    "CONCLAVE_DB_PATH", os.path.join(tempfile.gettempdir(), "conclave_test.db")
)
