# 工作区相关 DTO
from __future__ import annotations

from pydantic import BaseModel, Field

# 安全限制常量
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB 文件写入上限
MAX_CODE_SIZE = 100 * 1024  # 100KB 代码执行上限
MAX_COMMAND_LEN = 4096  # 4KB 命令长度上限
MAX_PATH_LEN = 1024  # 路径长度上限


class FileWriteRequest(BaseModel):
    """文件写入请求"""

    path: str = Field(..., min_length=1, max_length=MAX_PATH_LEN, description="工作区内相对路径")
    content: str = Field(..., max_length=MAX_FILE_SIZE, description="文件内容（最大5MB）")


class CodeRunRequest(BaseModel):
    """代码执行请求"""

    code: str = Field(..., max_length=MAX_CODE_SIZE, description="要执行的 Python 代码（最大100KB）")
    language: str = Field(default="python", max_length=32, description="语言（目前支持 python）")
    network_level: str = Field(
        default="L1", max_length=8, description="网络分级：L1=无网络(默认) / L2=限网(pip) / L3=全联网"
    )


class CommandRequest(BaseModel):
    """命令执行请求"""

    command: str = Field(..., min_length=1, max_length=MAX_COMMAND_LEN, description="要执行的命令（最大4KB）")
    cwd: str = Field(default="", max_length=MAX_PATH_LEN, description="工作目录（工作区内相对路径）")
    network_level: str = Field(
        default="L2", max_length=8, description="网络分级：L1=无网络 / L2=限网(默认,pip) / L3=全联网"
    )
