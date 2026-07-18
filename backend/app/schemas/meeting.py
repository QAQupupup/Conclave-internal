# 会议相关 DTO + VO
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CreateMeetingRequest(BaseModel):
    """创建会议请求"""
    topic: str = Field(..., min_length=1, max_length=500, description="会议议题")
    deliverable_type: str = Field("prd_openapi", description="产出类型: prd_openapi|design_doc|comprehensive|research_report|business_report|code_analysis|tested_system|deployable_service|execution")
    flow_plan: str = Field("standard", description="执行模式: instant(即时回答)|standard(标准六阶段)|plan(先计划后执行)")
    debate_depth: str = Field("standard", description="辩论深度: light|standard|deep")
    role_ids: list[str] = Field(default_factory=list, max_length=50, description="预选角色 ID 列表，为空则自动生成")
    reference_meeting_ids: list[str] = Field(default_factory=list, max_length=20, description="引用的历史会议 ID 列表")
    model: str = Field("", max_length=200, description="会议级模型覆盖（格式: provider_id:model_id 或纯 model_id），空=继承 ENV 默认")
    auto_iterate: bool = Field(False, description="是否自动迭代直到质量达标（仅对deployable_service等代码产出有效）")
    max_iterations: int = Field(2, ge=0, le=5, description="最大迭代轮次（0=不迭代）")
    max_stage_retries: int = Field(2, ge=0, le=5, description="每个阶段最大重试次数")


class CreateMeetingResponse(BaseModel):
    """创建会议响应"""
    meeting_id: str
    topic: str
    stage: str
    status: str


class ControlRequest(BaseModel):
    """控场信号请求"""
    signal: str = Field(..., description="控制信号: pause|resume|abort|inject|loan")
    payload: dict[str, Any] = Field(default_factory=dict)


class RunResponse(BaseModel):
    """运行结果响应"""
    meeting_id: str
    stage: str
    status: str
    artifact: dict[str, Any] | None = None
    messages_count: int = 0


class BatchDeleteRequest(BaseModel):
    """批量删除请求"""
    meeting_ids: list[str] = Field(..., description="待删除的会议 ID 列表")
    mode: str = Field("soft", description="删除模式: soft|hard")


class AddTagRequest(BaseModel):
    """添加标签请求"""
    tag: str = Field(..., min_length=1, max_length=32, description="标签名称")


class InjectReferenceRequest(BaseModel):
    """会议中注入历史会议引用请求"""
    reference_meeting_ids: list[str] = Field(..., description="要引用的历史会议 ID 列表")


class InterventionRequest(BaseModel):
    """用户介入对话请求"""
    content: str = Field(..., description="用户输入内容")
    reply_to_id: str | None = Field(None, description="回复的消息 ID")


class SetModelRequest(BaseModel):
    """设置会议模型请求"""
    provider_id: str = Field("", description="厂商ID: siliconflow|deepseek|openai|openrouter|custom")
    model: str = Field("", description="模型ID，如 deepseek-ai/DeepSeek-V3.2")
    api_key: str = Field("", description="自定义API Key（BYOK），为空则使用默认")
    base_url: str = Field("", description="自定义Base URL（provider_id=custom时使用）")


class SaveApiKeyRequest(BaseModel):
    """保存 API Key 请求"""
    provider: str = Field(..., description="厂商ID")
    api_key: str = Field(..., description="API Key 明文")
    name: str = Field(default="default", description="Key别名")
    base_url: str = Field(default="", description="自定义Base URL")
    is_default: bool = Field(default=True, description="是否设为默认")
