"""SQLAlchemy ORM 模型包。

从子模块 re-export 全部 14 个 ORM 模型。
Alembic 通过 ``from app.db.models import *`` 注册所有模型到 metadata。
"""

from __future__ import annotations

from app.db.models.agent_role import AgentRoleModel
from app.db.models.docker_host import DockerHostModel, DockerHostSecretModel
from app.db.models.document import DocumentModel
from app.db.models.event import EventModel
from app.db.models.meeting import MeetingAuxModel, MeetingModel, MeetingTagModel
from app.db.models.memory import FeatureMemoryModel, ProfileMemoryModel, RawMemoryModel
from app.db.models.message import MessageModel
from app.db.models.observability import CostRecordModel
from app.db.models.user import ApiKeyModel, UserPreferenceModel

__all__ = [
    "AgentRoleModel",
    "ApiKeyModel",
    "CostRecordModel",
    "DockerHostModel",
    "DockerHostSecretModel",
    "DocumentModel",
    "EventModel",
    "FeatureMemoryModel",
    "MeetingAuxModel",
    "MeetingModel",
    "MeetingTagModel",
    "MessageModel",
    "ProfileMemoryModel",
    "RawMemoryModel",
    "UserPreferenceModel",
]
