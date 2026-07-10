"""Repository 抽象接口层（ABC）。

定义所有持久化操作的契约，与具体存储后端解耦。
当前实现：SqlAlchemyRepository（PostgreSQL/SQLite 双后端）。
未来可扩展：OceanBaseRepository 等。

所有方法均为 async，返回 Pydantic Domain Models（非 ORM 对象）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class MeetingRepository(ABC):
    """会议 CRUD 抽象接口。"""

    @abstractmethod
    async def save(self, meeting_id: str, topic: str, status: str,
                   stage: str, created_at: datetime, payload: dict[str, Any],
                   schema_version: int = 1) -> None:
        """upsert 会议记录"""
        ...

    @abstractmethod
    async def get(self, meeting_id: str) -> dict[str, Any] | None:
        """取单条会议"""
        ...

    @abstractmethod
    async def list(self, include_deleted: bool = False) -> list[dict[str, Any]]:
        """列出全部会议"""
        ...

    @abstractmethod
    async def query(self, q: str | None = None, limit: int = 20,
                    offset: int = 0, tags: list[str] | None = None,
                    include_deleted: bool = False) -> dict[str, Any]:
        """搜索+分页+标签过滤"""
        ...

    @abstractmethod
    async def get_by_ids(self, meeting_ids: list[str]) -> list[dict[str, Any]]:
        """批量取会议摘要（用于历史会议引用）"""
        ...

    @abstractmethod
    async def soft_delete(self, meeting_id: str) -> bool:
        """软删除"""
        ...

    @abstractmethod
    async def hard_delete(self, meeting_id: str) -> bool:
        """硬删除"""
        ...

    @abstractmethod
    async def restore(self, meeting_id: str) -> bool:
        """恢复软删除的会议"""
        ...

    @abstractmethod
    async def recover_running(self) -> list[dict[str, Any]]:
        """查找 status=running 的会议（崩溃恢复）"""
        ...


class MessageRepository(ABC):
    """发言记录抽象接口。"""

    @abstractmethod
    async def save(self, msg: dict[str, Any]) -> None:
        """保存发言"""
        ...

    @abstractmethod
    async def list_by_meeting(self, meeting_id: str) -> list[dict[str, Any]]:
        """取某会议全部发言"""
        ...


class EventRepository(ABC):
    """事件溯源抽象接口。"""

    @abstractmethod
    async def save(self, meeting_id: str, event_type: str,
                   payload: dict[str, Any], ts: str,
                   trace_id: str | None = None) -> int:
        """持久化事件，返回 seq"""
        ...

    @abstractmethod
    async def load(self, meeting_id: str, from_seq: int = 0) -> list[dict[str, Any]]:
        """增量加载事件"""
        ...

    @abstractmethod
    async def last_seq(self, meeting_id: str) -> int:
        """取最后事件 seq"""
        ...


class TagRepository(ABC):
    """标签抽象接口。"""

    @abstractmethod
    async def list_all(self) -> list[dict[str, Any]]:
        """列出所有标签及使用次数"""
        ...

    @abstractmethod
    async def get_meeting_tags(self, meeting_id: str) -> list[str]:
        """取会议标签"""
        ...

    @abstractmethod
    async def add(self, meeting_id: str, tag: str) -> bool:
        """添加标签"""
        ...

    @abstractmethod
    async def remove(self, meeting_id: str, tag: str) -> bool:
        """移除标签"""
        ...

    @abstractmethod
    async def batch_delete(self, meeting_ids: list[str],
                           mode: str = "soft") -> dict[str, list[str]]:
        """批量删除会议"""
        ...


class PreferenceRepository(ABC):
    """用户偏好抽象接口。"""

    @abstractmethod
    async def get(self, user_id: str, key: str) -> str | None:
        """取单条偏好"""
        ...

    @abstractmethod
    async def set(self, user_id: str, key: str, value: str) -> str:
        """upsert 偏好，返回 updated_at"""
        ...

    @abstractmethod
    async def get_all(self, user_id: str) -> dict[str, str]:
        """取全部偏好"""
        ...

    @abstractmethod
    async def delete(self, user_id: str, key: str) -> bool:
        """删除偏好"""
        ...


class AgentRoleRepository(ABC):
    """Agent 角色抽象接口。"""

    @abstractmethod
    async def list(self, active_only: bool = False) -> list[dict[str, Any]]:
        """列出角色"""
        ...

    @abstractmethod
    async def get(self, role_id: str) -> dict[str, Any] | None:
        """取单个角色"""
        ...

    @abstractmethod
    async def save(self, role: dict[str, Any]) -> None:
        """upsert 角色"""
        ...

    @abstractmethod
    async def delete(self, role_id: str) -> bool:
        """删除角色（内置角色不可删）"""
        ...

    @abstractmethod
    async def get_by_ids(self, role_ids: list[str]) -> list[dict[str, Any]]:
        """批量取角色"""
        ...


class NetAuthRepository(ABC):
    """网络授权申请抽象接口。"""

    @abstractmethod
    async def create_request(self, request_id: str, meeting_id: str,
                             stage: str, code_snippet: str,
                             requested_level: str, detected_level: str,
                             failure_reason: str, stderr_output: str,
                             expires_at: datetime) -> None:
        """创建授权申请"""
        ...

    @abstractmethod
    async def get(self, request_id: str) -> dict[str, Any] | None:
        """取单条申请"""
        ...

    @abstractmethod
    async def list_by_meeting(self, meeting_id: str,
                              status: str | None = None) -> list[dict[str, Any]]:
        """列出申请单"""
        ...

    @abstractmethod
    async def review(self, request_id: str, action: str,
                     comment: str) -> dict[str, Any] | None:
        """批复申请"""
        ...

    @abstractmethod
    async def expire_pending(self) -> list[dict[str, Any]]:
        """过期超时申请"""
        ...

    @abstractmethod
    async def get_pending(self, meeting_id: str) -> list[dict[str, Any]]:
        """取某会议 pending 申请"""
        ...