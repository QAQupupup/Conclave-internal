"""会议生命周期钩子 Mixin。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from app.plugins.core.types import Fallback, Next, PluginContext


@runtime_checkable
class MeetingCreatingMixin(Protocol):
    """会议创建前拦截钩子（拦截型）。

    - 返回 Fallback: 阻止创建（返回 HTTP 错误）
    - 返回 Next/None: 继续；可通过 ctx.extra['metadata_patch'] 注入 metadata 片段
    """

    async def on_meeting_creating(self, ctx: PluginContext, payload: dict) -> Next | Fallback | None: ...


@runtime_checkable
class MeetingCreatedMixin(Protocol):
    """会议创建后观察钩子（观察型）。用于审计日志、通知。"""

    async def on_meeting_created(self, ctx: PluginContext, meeting_id: str, metadata: dict) -> None: ...


@runtime_checkable
class MeetingAccessMixin(Protocol):
    """会议访问拦截钩子（拦截型）。返回 Fallback 拒绝访问。"""

    async def on_meeting_accessing(self, ctx: PluginContext, meeting: Any) -> Next | Fallback | None: ...
