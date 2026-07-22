"""插件钩子 Mixin 协议。"""

from __future__ import annotations

from app.plugins.core.hooks.lifecycle import LifecycleMixin, MiddlewareMixin, RouterMixin
from app.plugins.core.hooks.llm import (
    LLMErrorInfo,
    LLMErrorMixin,
    LLMObserverMixin,
    LLMPreCallMixin,
    LLMRequest,
    LLMResponse,
    LLMUsage,
)
from app.plugins.core.hooks.meeting import (
    MeetingAccessMixin,
    MeetingCreatedMixin,
    MeetingCreatingMixin,
)
from app.plugins.core.types import (
    Fallback,
    LLMFallback,
    LLMOverride,
    Next,
    Override,
)

__all__ = [
    "Fallback",
    "LLMErrorInfo",
    "LLMErrorMixin",
    "LLMFallback",
    "LLMObserverMixin",
    "LLMOverride",
    "LLMPreCallMixin",
    "LLMRequest",
    "LLMResponse",
    "LLMUsage",
    "LifecycleMixin",
    "MeetingAccessMixin",
    "MeetingCreatedMixin",
    "MeetingCreatingMixin",
    "MiddlewareMixin",
    "Next",
    "Override",
    "RouterMixin",
]
