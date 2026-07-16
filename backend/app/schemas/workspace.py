# 工作区相关 DTO
from __future__ import annotations

from pydantic import BaseModel, Field


class FileWriteRequest(BaseModel):
    """文件写入请求"""
    path: str = Field(..., description="工作区内相对路径")
    content: str = Field(..., description="文件内容")


class CodeRunRequest(BaseModel):
    """代码执行请求"""
    code: str = Field(..., description="要执行的 Python 代码")
    language: str = Field(default="python", description="语言（目前支持 python）")
    network_level: str = Field(default="L1", description="网络分级：L1=无网络(默认) / L2=限网(pip) / L3=全联网")


class CommandRequest(BaseModel):
    """命令执行请求"""
    command: str = Field(..., description="要执行的命令")
    cwd: str = Field(default="", description="工作目录（工作区内相对路径）")
    network_level: str = Field(default="L2", description="网络分级：L1=无网络 / L2=限网(默认,pip) / L3=全联网")
