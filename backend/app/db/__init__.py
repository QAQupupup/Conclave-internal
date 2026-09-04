# app/db/ — 持久化层
# 架构：engine.py (async engine / AsyncSession 工厂) + base.py (DeclarativeBase) + models/ (ORM 模型包)
# 建表入口：Base.metadata.create_all()（新库）+ Alembic 迁移（增量），见 docs/sql-development-rules.md §5
# 向量存储：VectorStore(ABC) → QdrantVectorStore（当前）/ PgvectorVectorStore（备选）
# ORM 模型：models/ 包（meeting/message/event/memory/observability 等，供 Alembic 迁移与 DAO 查询）
