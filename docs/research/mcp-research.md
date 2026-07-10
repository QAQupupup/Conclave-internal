# MCP 服务器协议预研

> 本文为 MCP（Model Context Protocol）集成的预研文档，作为阶段三的远期规划。
> 目标：让 Conclave 能够挂载外部知识库（如开源文档管理系统），实现交叉映射。

## 1. 什么是 MCP

MCP（Model Context Protocol）是 Anthropic 提出的开放协议，用于让 AI 应用与外部数据源/工具进行标准化交互。核心概念：

- **MCP Server**：暴露资源（resources）、提示（prompts）、工具（tools）的服务端
- **MCP Client**：连接 MCP Server 并消费其能力的客户端
- **Transport**：stdio / SSE / HTTP

## 2. Conclave 集成 MCP 的场景

### 2.1 知识库挂载（读取）
- 将开源文档管理系统（如 Outline、BookStack、Wiki.js）作为 MCP Server
- Conclave 作为 Client，会议过程中检索知识库内容作为证据
- 替代当前的 RAG（文档上传 → 切块 → embedding），改为实时 MCP 查询

### 2.2 会议结果沉淀（写入）
- 会议产出的 PRD、设计文档、代码规范存入知识库
- 后续会议可直接引用历史会议结论
- 形成"会议 → 知识库 → 会议"的闭环

### 2.3 审核检查点（执行）
- 系统读取知识库中的代码风格规范
- 在 produce 阶段对生成的代码做自动审核
- 不符合规范时自动修正或标记

## 3. 架构设计（预留）

```
┌─────────────┐     MCP Protocol     ┌──────────────┐
│  Conclave   │◄──────────────────►│  MCP Server   │
│  (Client)   │   resources/tools   │  (知识库)     │
└─────────────┘                     └──────────────┘
       │
       │ MCP Protocol
       ▼
┌──────────────┐
│  MCP Server   │
│  (代码规范)   │
└──────────────┘
```

### 3.1 MCP Client 抽象（需实现）

```python
# backend/app/mcp/client.py（预研，未实现）
from typing import Protocol

class MCPServerPort(Protocol):
    """MCP Server 端口：定义 Conclave 与外部知识库的交互契约"""
    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        """检索知识库内容"""
        ...

    async def read_resource(self, uri: str) -> str:
        """读取知识库资源"""
        ...

    async def write_resource(self, uri: str, content: str) -> bool:
        """写入知识库（会议结果沉淀）"""
        ...

class MCPClient:
    """MCP Client：连接多个 MCP Server，统一管理"""
    def __init__(self):
        self._servers: dict[str, MCPServerPort] = {}

    def register(self, name: str, server: MCPServerPort):
        self._servers[name] = server

    async def search_all(self, query: str) -> dict[str, list[dict]]:
        """并行查询所有已注册的 MCP Server"""
        ...
```

### 3.2 与现有 RAG 的关系

| 维度 | 当前 RAG | MCP 集成后 |
|---|---|---|
| 数据来源 | 用户上传 .md 文件 | 外部知识库实时查询 |
| 检索方式 | embedding + reranker | MCP search（服务端实现） |
| 数据时效 | 会议开始时上传 | 实时最新 |
| 写入闭环 | 无 | 会议结果存入知识库 |
| 适用场景 | 单次会议 | 跨会议知识积累 |

**演进路径**：MCP 不是替换 RAG，而是作为 RAG 的数据源之一。RAG 层的 Chunk 结构化（metadata/claims/relations）为 MCP 查询结果的格式化提供了基础。

## 4. 实现路径（远期）

1. **Phase 1**：实现 MCP Client 基础框架（连接、search、read_resource）
2. **Phase 2**：接入第一个 MCP Server（如 Outline 文档系统）
3. **Phase 3**：实现 write_resource（会议结果沉淀到知识库）
4. **Phase 4**：在 evidence_check 阶段集成 MCP 查询作为额外证据来源
5. **Phase 5**：在 produce 阶段集成 MCP 读取代码规范做审核

## 5. 依赖

- Python MCP SDK：`mcp` 包（pip install mcp）
- 需要外部 MCP Server 实例（Outline / BookStack / 自建）

## 6. 当前状态

- **本文档为预研**，未实现任何 MCP 代码
- DAG 任务图（`task_graph.py`）已实现，为多 Agent 并行执行提供基础
- MCP 集成需要外部 MCP Server，建议在知识库系统就绪后再推进
