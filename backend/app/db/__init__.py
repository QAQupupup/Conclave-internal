# app/db/ — 持久化层
# 架构：db_legacy.py (psycopg2 原生 SQL，实际主力) + engine.py (AsyncSession 工厂)
# 向量存储：VectorStore(ABC) → QdrantVectorStore（当前）/ PgvectorVectorStore（备选）
# ORM 模型：models.py (14 张表定义，用于 Alembic 迁移和 router 只读查询)
