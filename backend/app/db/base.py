"""SQLAlchemy ORM 基类。

所有 ORM 模型继承自 Base，通过 Base.metadata 统一管理表结构。
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """ORM 模型基类。"""

    pass
