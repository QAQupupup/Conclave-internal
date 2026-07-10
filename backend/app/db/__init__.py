# app/db/ — 持久化层
# 架构：engine → session_factory → Repository(ABC) → SqlAlchemyRepository
# 向量存储：VectorStore(ABC) → QdrantVectorStore（当前）/ PgvectorVectorStore（备选）