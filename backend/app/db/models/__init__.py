"""SQLAlchemy ORM 模型包。

从子模块 re-export 全部 14 个 ORM 模型。
Alembic 通过 ``from app.db.models import *`` 注册所有模型到 metadata。
"""
from __future__ import annotations

from app.db.models.meeting import MeetingModel, MeetingTagModel, MeetingAuxModel
from app.db.models.message import MessageModel
from app.db.models.event import EventModel
from app.db.models.user import UserPreferenceModel, ApiKeyModel
from app.db.models.agent_role import AgentRoleModel
from app.db.models.net_auth import NetAuthRequestModel
from app.db.models.document import DocumentModel
from app.db.models.observability import CostRecordModel
from app.db.models.memory import RawMemoryModel, FeatureMemoryModel, ProfileMemoryModel

__all__ = [
    "MeetingModel", "MeetingTagModel", "MeetingAuxModel",
    "MessageModel",
    "EventModel",
    "UserPreferenceModel", "ApiKeyModel",
    "AgentRoleModel",
    "NetAuthRequestModel",
    "DocumentModel",
    "CostRecordModel",
    "RawMemoryModel", "FeatureMemoryModel", "ProfileMemoryModel",
]
