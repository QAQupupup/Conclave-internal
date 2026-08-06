"""SQLAlchemy ORM 模型包。

从子模块 re-export 全部 ORM 模型。
Alembic 通过 ``from app.db.models import *`` 注册所有模型到 metadata。
"""

from __future__ import annotations

from app.db.models.agent_role import AgentRoleModel
from app.db.models.docker_host import DockerHostModel, DockerHostSecretModel
from app.db.models.document import DocumentModel
from app.db.models.event import EventModel
from app.db.models.graph import (
    ChunkEntityModel,
    DocumentRelationModel,
    EntityModel,
    GraphEdgeModel,
)
from app.db.models.meeting import MeetingAuxModel, MeetingModel, MeetingTagModel
from app.db.models.memory import FeatureMemoryModel, ProfileMemoryModel, RawMemoryModel
from app.db.models.message import MessageModel
from app.db.models.observability import AuditLogModel, CostRecordModel
from app.db.models.tenant import TenantModel
from app.db.models.tenant_member import TenantMemberModel
from app.db.models.user import ApiKeyModel, UserPreferenceModel, UserSettingModel
from app.db.models.user_account import UserModel

__all__ = [
    "AgentRoleModel",
    "ApiKeyModel",
    "AuditLogModel",
    "ChunkEntityModel",
    "CostRecordModel",
    "DockerHostModel",
    "DockerHostSecretModel",
    "DocumentModel",
    "DocumentRelationModel",
    "EntityModel",
    "EventModel",
    "FeatureMemoryModel",
    "GraphEdgeModel",
    "MeetingAuxModel",
    "MeetingModel",
    "MeetingTagModel",
    "MessageModel",
    "ProfileMemoryModel",
    "RawMemoryModel",
    "TenantMemberModel",
    "TenantModel",
    "UserModel",
    "UserPreferenceModel",
    "UserSettingModel",
]
