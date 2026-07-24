# Conclave 架构选型决策

[返回项目主页](README.md)

本文档记录 Conclave 在每个技术维度上的选型决策：选了什么、淘汰了什么、为什么。所有决策基于"多智能体结构化决策系统"的核心场景。

---

## 目录

1. [整体哲学](#整体哲学)
2. [后端框架](#后端框架)
3. [Agent 编排范式](#agent-编排范式)
4. [数据库与存储](#数据库与存储)
5. [向量检索方案](#向量检索方案)
6. [嵌入与重排序模型](#嵌入与重排序模型)
7. [缓存与消息传递](#缓存与消息传递)
8. [前端技术栈](#前端技术栈)
9. [沙箱隔离方案](#沙箱隔离方案)
10. [容器化与部署](#容器化与部署)
11. [认证与多租户](#认证与多租户)
12. [浏览器自动化](#浏览器自动化)
13. [ORM 与数据迁移](#orm-与数据迁移)
14. [测试策略](#测试策略)
15. [代码质量工具](#代码质量工具)

---

## 整体哲学

选型核心原则（按优先级）：

1. **本地可部署优先**：不依赖任何 SaaS 服务，一条 `docker compose up` 跑完全栈
2. **asyncio 原生**：全链路异步，从 HTTP 到 DB 到 LLM 调用不阻塞事件循环
3. **证据诚实性**：宁可降级置信度标注"证据不足"，也不编造伪引用
4. **运维极简**：一个 compose 文件、三个基础服务（PG/Redis/Qdrant），不引入重型基础设施
5. **国产环境友好**：所有镜像、pip 包、npm 包均配置国内镜像源

---

## 后端框架

**选型：FastAPI + Starlette + Uvicorn（Python 生态）**

> 项目从一开始就锁定 Python 技术栈：LLM/AI 生态（openai SDK、qdrant-client、playwright、jieba、sentence-transformers 等）以 Python 为第一优先级，非 Python 方案直接不纳入候选。

| 候选方案 | 优势 | 劣势 | 结论 |
|---|---|---|---|
| **FastAPI** | 原生 async/await、Pydantic 数据校验、自动 OpenAPI 文档、性能接近 Starlette 原生、生态成熟 | 相对 Django"裸"一些，需自行组装 ORM/认证/迁移 | ✅ 选用 |
| Django + Django REST Framework | 一站式（ORM/Admin/认证/迁移全有）、成熟稳定 | WSGI 同步模型，async 支持是后加的，对 asyncio 原生不友好；强约定难定制 Agent 编排逻辑 | ❌ 淘汰（asyncio 是硬需求） |
| Flask + Quart | 轻量灵活 | Flask 本身同步；Quart 生态小，缺少 Pydantic 校验和自动文档 | ❌ 淘汰（生态不足） |

**不纳入候选的方案**：
- Java/Spring Boot：体系偏重、语法繁琐、启动慢内存大，与项目"轻量本地部署"理念不符
- Node.js：团队对 Node.js 后端生态熟练度不足，且 AI/LLM SDK 质量以 Python 为优

**决策理由**：Conclave 本质是 AI 应用，必须站在 Python AI 生态的肩膀上。FastAPI 在 Python Web 框架中 asyncio 原生度最高，Pydantic 模型可直接复用于 LLM 输出校验，自动生成的 OpenAPI 文档也降低了前后端联调成本。

---

## Agent 编排范式

**选型：自研六阶段管线（clarify → intra_team → cross_team → evidence_check → arbitrate → produce）**

| 候选方案 | 优势 | 劣势 | 结论 |
|---|---|---|---|
| **自研管线** | 完全控制决策流程、质量门禁可硬编码、证据校验节点可强制执行、阶段间可做上下文裁剪与 Token 预算 | 需要自己实现调度/重试/回流，开发量大 | ✅ 选用 |
| LangChain / LangGraph | 生态最大、组件丰富、图编排灵活 | 抽象层过多、调试困难、版本迭代快导致 API breaking change、Token 管理和质量门禁需自己实现 | ❌ 淘汰（黑盒过多，难保证证据诚实性） |
| AutoGen (Microsoft) | 多角色对话原生支持、GroupChat 抽象好 | 对话式编排难以强制结构化质量门禁、对 produce 阶段"可交付物"支持弱 | ❌ 淘汰（偏对话，偏研究原型） |
| CrewAI | 角色定义直观、上手快 | 封装层厚、自定义流程困难、对证据校验/仲裁/质量评分支持不足 | ❌ 淘汰（灵活性不足） |
| Semantic Kernel | 企业级、插件机制好 | .NET/TypeScript 优先，Python 生态次之；对会议式结构化决策场景抽象不对口 | ❌ 淘汰（场景不匹配） |

**决策理由**：Conclave 的核心价值主张是"有流程、有证据、有裁决、有交付"的高质量决策。这四个环节任何一个做不好都会沦为普通对话。通用 Agent 框架追求通用性，不会为你强制实施证据校验或仲裁裁决，必须在框架之上再搭一层。我们选择直接在 FastAPI 上实现管线，把质量门禁（8 维评分、自动回流补充、漂移检查）写死在编排层，这才是产品的核心竞争力。

参考设计见 [orchestrator/README.md](backend/app/orchestrator/README.md)。

---

## 数据库与存储

**选型：PostgreSQL 15+（含 pgvector，当前过渡方案）**

| 候选方案 | 优势 | 劣势 | 结论 |
|---|---|---|---|
| **PostgreSQL** | 成熟可靠、JSONB 支持灵活扩展（ADR-002）、pgvector 可直接存向量、事务强一致、Docker 镜像小、开源生态活跃 | 单点写入瓶颈（对 Conclave 场景足够）；JSONB 查询性能不如原生列 | ✅ 现阶段选用 |
| MySQL | 普及度高、云服务多 | MySQL 已非真正开源（Oracle 控制下的双许可，社区版功能受限）；JSONB 功能弱于 PG；向量支持不成熟；生态走向不确定性高 | ❌ 淘汰（非真正开源 + 向量/JSON 弱） |
| MongoDB | 文档模型灵活、Schema-free | 无强事务、无向量能力、聚合管道复杂、数据一致性弱 | ❌ 淘汰（需要事务+向量） |
| SQLite | 零配置、嵌入式 | 无并发写入能力、不适合多用户 Web 服务 | ❌ 淘汰（只适合单用户桌面） |
| OceanBase（MySQL 兼容） | 国产开源、金融级高可用、原生分布式、HTAP、MySQL 兼容 | 目前 Docker 部署仍偏重、生态成熟度待观察 | 📋 未来候选 |
| OceanBase SequoiaDB（Seek DB） | OceanBase 向量数据库、与 OceanBase 生态一体化 | 尚未正式发布稳定版、生态待验证 | 📋 未来候选 |

**决策理由**：
- **为什么不是 MySQL**：MySQL 在 Oracle 旗下已非真正开源方案，社区版受许可限制越来越多，长期看不是可靠的开源选择。
- **为什么选 PostgreSQL（过渡）**：PostgreSQL 的 JSONB 完美匹配"非核心字段走 metadata"的扩展策略（ADR-002），pgvector 提供向量 fallback，强事务对会议状态机至关重要，且生态最活跃、开箱即用。
- **未来规划**：OceanBase 开源生态持续成熟（MySQL 兼容版 + SequoiaDB 向量能力）后，可考虑从 PostgreSQL 迁移至 OceanBase 体系，统一关系存储与向量检索能力。

参考 [db/README.md](backend/app/db/README.md) 和 `docs/design/adr/002-jsonb-metadata.md`。

---

## 向量检索方案

**选型：Qdrant（生产）+ 内存向量库（开发模式）**

| 候选方案 | 优势 | 劣势 | 结论 |
|---|---|---|---|
| **Qdrant** | Rust 写的高性能向量数据库、原生支持过滤检索、Docker 镜像小（~80MB）、REST/gRPC 双协议、支持 HNSW 索引、开源版功能完整 | 需要额外一个容器 | ✅ 选用（生产） |
| Milvus / Zilliz | 云原生、大规模（亿级向量）、性能强 | 架构重（etcd/MinIO/Pulsar 一堆依赖）、单机模式也占资源多、运维复杂 | ❌ 淘汰（太重） |
| Weaviate | 模块化（内置嵌入模型/重排序/问答）、GraphQL API | 模块捆绑导致灵活性差、JVM 启动慢内存大、定制嵌入模型麻烦 | ❌ 淘汰（JVM 重，捆绑模型） |
| Chroma | Python 原生、轻量、开发友好 | 性能不适合生产、单机存储、并发能力弱 | ❌ 淘汰（仅适合 notebook 原型） |
| Pinecone / Weaviate Cloud | 托管服务、零运维 | SaaS 依赖、数据出私域、成本随规模上涨、违反"本地可部署"原则 | ❌ 淘汰（SaaS 依赖红线） |
| pgvector | 与 PG 一体、无额外服务、部署最简 | 向量性能不如专用库、过滤检索能力弱、HNSW 参数调优不灵活；更关键的是 pgvector 与数据库版本/扩展绑定较紧，embedding 维度变更、索引重建等运维操作与业务数据耦合，嵌入方案切换成本高（换 embedding 模型要重建整个 PG 扩展索引） | ❌ 淘汰（作为开发 fallback 保留，不作为主存储） |
| **内存向量库** | 零依赖、启动快 | 数据不持久、重启丢失、性能有限 | ✅ 选用（开发模式 fallback） |

**决策理由**：Qdrant 是当前开源向量数据库中"轻量 + 高性能 + 功能完整"的最佳平衡点。Docker 镜像仅 80MB，一个容器启动 3 秒可用，HNSW 索引性能完全覆盖 Conclave 的文档规模（千级到万级 chunk）。更重要的是，独立向量库将 embedding 维度、索引策略、数据生命周期与业务数据库解耦，切换 embedding 模型（如从 bge-m3 换到未来新模型）时只需重建向量集合，不影响 PG 业务数据。内存向量库作为开发模式 fallback，让开发者不需要 Qdrant 也能跑基本流程。

参考 [rag/README.md](backend/app/rag/README.md)。

---

## 嵌入与重排序模型

**选型：bge-m3（嵌入）+ bge-reranker-v2-m3（重排序），通过 SiliconFlow 等 OpenAI 兼容 API 调用**

| 候选方案 | 优势 | 劣势 | 结论 |
|---|---|---|---|
| **bge-m3** | 多语言（中英及 100+ 语言）、1024 维、支持稠密+稀疏+多向量三种检索模式、开源权重可本地部署、MTEB 中文榜前列；**在硅基流动（SiliconFlow）上免费调用** | 模型较大（~2GB FP16，本地部署时） | ✅ 选用 |
| text-embedding-ada-002 / text-embedding-3-large (OpenAI) | API 稳定、文档丰富、无需 GPU | 英文主导、中文效果一般、SaaS 依赖、付费、成本随规模涨 | ❌ 淘汰（中文效果 + 付费 SaaS） |
| m3e / m3e-large | 中文专门优化、轻量 | 多语言支持弱、MTEB 整体不如 bge-m3、社区活跃度低、无大规模免费 API 可用 | ❌ 淘汰（通用性弱 + 无免费 API） |
| e5-large-v2 / e5-mistral | 英文效果好 | 中文弱、需要指令前缀、多语言版本推理成本高 | ❌ 淘汰（中文弱） |
| **bge-reranker-v2-m3** | 跨语言重排序、LLM 级精度但为 cross-encoder 小模型、与 bge-m3 配套；**在硅基流动上免费调用** | 推理比向量检索慢（批量重排序 top-50 约 100-200ms） | ✅ 选用 |
| cohere rerank | API 质量高 | SaaS 依赖、中文效果一般、付费 | ❌ 淘汰（SaaS 依赖 + 付费） |
| bge-reranker-v2-gemma / bge-reranker-large | LLM-based rerank 精度更高 | 模型太大（7B+）推理慢、需 GPU、无免费 API | ❌ 淘汰（推理成本高） |

**决策理由**：BAAI（智源）的 bge 系列是当前中英双语场景的最佳开源选择，bge-m3 同时支持稠密/稀疏/ColBERT 三种检索模式，为后续混合检索升级留足空间。**关键加分项**：bge-m3 和 bge-reranker-v2-m3 在硅基流动（SiliconFlow）平台上提供免费 API 调用，零成本即可启动 RAG 能力，完美匹配"一条命令本地启动"的理念。同时模型权重开源，未来如需本地部署可无缝切换。StubEmbedding + KeywordReranker 作为无 API Key 时的开发 fallback。

---

## 缓存与消息传递

**选型：Redis 7（缓存 + Pub/Sub 多副本广播）**

| 候选方案 | 优势 | 劣势 | 结论 |
|---|---|---|---|
| **Redis** | 内存 KV、Pub/Sub 原生、数据结构丰富（List/Hash/Stream）、Docker 镜像小、生态成熟 | Pub/Sub 不持久（断线丢消息）、Stream 复杂 | ✅ 选用 |
| RabbitMQ | 消息队列专业级、持久化、确认机制 | 镜像较大（~200MB）、Erlang 运行时、对"实时广播"场景过重 | ❌ 淘汰（不需要消息持久化，事件已落 PG） |
| Kafka | 高吞吐、持久化日志 | 需要 Zookeeper/KRaft+Broker、运维重、对实时 UI 推送场景杀鸡用牛刀 | ❌ 淘汰（过度设计） |
| NATS | 轻量（~20MB）、高性能 | 生态不如 Redis、缺少 KV 缓存能力（需要两套系统） | ❌ 淘汰（功能单一） |
| PostgreSQL LISTEN/NOTIFY | 零额外依赖 | 不支持多副本 fan-out、无缓存能力、频道管理弱 | ❌ 淘汰（能力不足） |
| 纯内存 EventBus | 零依赖、最快 | 多副本部署时无法跨进程广播、重启丢失 | ❌ 淘汰（仅作为 PG+Redis 前的 L1 缓存） |

**决策理由**：Conclave 的事件总线采用三层架构：内存缓存（L1，同进程最快）→ PostgreSQL 持久化（可靠存储+断线回放）→ Redis Pub/Sub（L3，多副本广播）。Redis 同时承担了会话缓存和跨副本广播两个角色，一个容器解决两个问题，运维最简。RabbitMQ/Kafka 在这个场景下是过度设计——我们不需要消息持久化（事件已经写 PG 了），只需要"正在发生的事"能广播到所有 WebSocket 连接。

---

## 前端技术栈

**选型：React 18 + TypeScript + Vite + 自定义 CSS 组件库**

| 候选方案 | 优势 | 劣势 | 结论 |
|---|---|---|---|
| **React 18 + TS + Vite** | 生态最大、Concurrent Mode、Suspense、Vite HMR 快、TS 类型安全 | 函数组件 + Hooks 学习曲线、需要自己搭组件库 | ✅ 选用 |
| Vue 3 + Element Plus / Ant Design Vue | 上手快、模板直观、中文生态好 | 大型应用的类型推导不如 TSX、React 生态（D3/可视化/复杂交互）更丰富 | ❌ 淘汰（复杂交互场景 React 更成熟） |
| Svelte / SvelteKit | 编译时优化、包小、写起来简洁 | 生态小、复杂状态管理案例少、团队经验不足 | ❌ 淘汰（生态风险） |
| SolidJS / Preact | 性能好 | 生态小、组件库少 | ❌ 淘汰（生态风险） |
| **自定义 CSS**（无 UI 框架） | 完全控制视觉风格、包体积极小（无框架 JS）、风格统一（严格遵循 `ui_design_system.yaml`） | 需要自己写基础组件（Button/Modal/Tabs） | ✅ 选用 |
| Ant Design | 组件最全、企业级成熟 | 默认风格重定制难、包大（~300KB gzipped）、视觉风格与 Conclave 的"沉稳靛蓝 + 极轻阴影"设计语言冲突 | ❌ 淘汰（风格冲突、过重） |
| shadcn/ui | 复制粘贴式组件、Tailwind 美观 | 依赖 Tailwind、组件风格偏 SaaS 营销页、需要 Radix UI 依赖 | ❌ 淘汰（Tailwind 与严格设计 token 体系冲突） |
| MUI (Material UI) | 组件全、定制性强 | Material Design 风格辨识度低、包大 | ❌ 淘汰（风格不匹配） |

**决策理由**：Conclave 的 UI 是高度定制化的"专业工具"风格（深色日志面板、六阶段进度条、实时拓扑图、可折叠面板），通用 UI 框架的组件抽象反而碍事。我们选择零 UI 框架依赖，用 CSS 变量 + 自定义组件严格遵循设计系统（见 `backend/app/skills/ui_design_system.yaml`），包体积和视觉一致性都有保障。Vite 是目前最快的前端构建工具，HMR 体验远超 Webpack/CRA。

参考 [frontend/README.md](frontend/README.md)。

---

## 沙箱隔离方案

**选型：Docker Sibling Containers + Socket Proxy + 三级网络隔离**

| 候选方案 | 优势 | 劣势 | 结论 |
|---|---|---|---|
| **Docker Sibling Containers** | 不依赖特权容器、与宿主机共享 Docker daemon 性能好、镜像可复用、支持多主机调度 | 需要挂载 Docker socket（通过 proxy 限制权限） | ✅ 选用 |
| Docker-in-Docker (DinD) | 完全隔离、不暴露宿主机 socket | 需要 `--privileged`、性能差（嵌套 FS）、存储驱动问题、镜像不能复用 | ❌ 淘汰（特权容器不安全） |
| Firecracker microVM | 强隔离（毫秒级启动 VM）、AWS Lambda 同款 | 需要 KVM（非所有环境支持，尤其 Windows/Mac Docker Desktop）、运维复杂、无 Docker 网络集成 | ❌ 淘汰（环境兼容性差） |
| gVisor | 用户态内核、强隔离 | 性能开销大、与 Docker Desktop 兼容性问题、系统调用覆盖不全 | ❌ 淘汰（兼容性问题） |
| subprocess / exec | 最简单、零依赖 | 无隔离，代码可访问宿主文件系统和网络，极度危险 | ❌ 淘汰（安全红线） |
| WebAssembly (Wasmtime/Wasmer) | 轻量沙箱、启动快 | 无法运行任意代码（需编译到 WASM）、无法部署 Docker 服务、生态不成熟 | ❌ 淘汰（无法交付可部署服务） |

**三级网络隔离**：
- L1 `--network none`：完全离线，纯计算任务
- L2 自定义网络 + dnsmasq 白名单：仅允许访问 pip/npm 等白名单域名
- L3 全联网：需用户显式授权

**Socket Proxy**：通过 `tecnativa/docker-socket-proxy` 限制 Docker API 暴露面，只开放 CONTAINERS/IMAGES/BUILD/NETWORKS/VOLUMES 等必要端点，禁止 EXEC/COMMIT/SWARM/SECRETS 等危险操作。

参考 [tools/README.md](backend/app/tools/README.md)。

---

## 容器化与部署

**选型：Docker Compose（多阶段构建）**

| 候选方案 | 优势 | 劣势 | 结论 |
|---|---|---|---|
| **Docker Compose** | 一条命令启动全栈、开发/测试/生产配置统一、多阶段构建减小镜像体积、门槛最低 | 单节点、无自动扩缩容 | ✅ 选用 |
| Kubernetes (K8s) | 自动扩缩容、滚动更新、服务网格 | 运维复杂度极高、本地开发需要 minikube/kind 等额外工具、对目标用户（中小团队/个人）门槛太高 | ❌ 淘汰（过度设计） |
| Docker Swarm | Docker 原生、比 K8s 简单 | 生态已停滞、功能弱 | ❌ 淘汰（弃坑状态） |
| Nomad | 轻量编排 | 生态小、需要额外学习 | ❌ 淘汰（用户门槛） |
| 直接 systemd + 裸机 | 性能最好、无虚拟化开销 | 环境配置复杂、跨平台难、依赖手动管理 | ❌ 淘汰（门槛高） |

**决策理由**：Conclave 的目标用户是希望"一条命令启动"的中小团队和个人开发者。Docker Compose 是最符合"零配置启动"原则的方案。多阶段构建将后端镜像控制在合理体积，开发/OSS/测试三套 Compose 文件（`docker-compose.yml`/`docker-compose.oss.yml`/`docker-compose.test.yml`）通过命名空间（conclave-dev/conclave-oss/conclave-test）实现环境隔离。

---

## 认证与多租户

**选型：JWT + HttpOnly Cookie + CSRF（CORE 插件，已实现行级多租户隔离）**

| 候选方案 | 优势 | 劣势 | 结论 |
|---|---|---|---|
| **JWT + HttpOnly Cookie + CSRF** | 无状态、支持横向扩展、HttpOnly 防 XSS、CSRF Token 防跨站、插件化实现 | 需要自己实现刷新/过期逻辑 | ✅ 选用 |
| Session + Redis | 简单、可随时吊销 | 有状态、多副本需要粘滞会话或 Redis 共享、对纯 JWT 场景不必要 | ❌ 淘汰（JWT 更适合多副本） |
| OAuth2 / OIDC（Auth0/Keycloak） | 标准协议、支持第三方登录 | Keycloak 运维重（需额外容器+数据库）、Auth0 是 SaaS 违反本地部署原则 | ❌ 淘汰（过度设计 + SaaS 依赖） |
| API Key | 最简单 | 无用户概念、无法做 RBAC、不适合 Web 界面 | ❌ 淘汰（功能不足） |

**多租户（已实现）**：所有业务表带 `tenant_id` 列（行级隔离），通过 `TenantScopeMixin` 自动注入；DAO 层通过 `_BUSINESS_TABLES` 注册后由 `ensure_business_tables_tenant_id()` 自动迁移加列；租户上下文通过 `ContextVar`（`current_tenant_id()`）传递，系统操作用 `create_system_tenant_ctx()` 包裹。外键统一 `ON DELETE SET NULL` 避免级联删除风险。参考 AGENTS.md §4.13 多租户 Checklist。

参考 [plugins/README.md](backend/app/plugins/README.md) 中 auth 插件章节。

---

## 浏览器自动化

**选型：Playwright + Chromium（Sibling Container 内运行）**

| 候选方案 | 优势 | 劣势 | 结论 |
|---|---|---|---|
| **Playwright** | 微软维护、自动等待、多浏览器支持、反检测能力强、`playwright-stealth` 生态好、网络拦截 API 强 | 镜像较大（需装 Chromium 依赖约 300MB） | ✅ 选用 |
| Selenium | 老牌、文档多 | API 笨重、需要 WebDriver、反检测弱、执行慢 | ❌ 淘汰（API 落后） |
| Puppeteer | Google 维护、Chromium 原生 | 仅支持 Chromium、反检测弱于 Playwright、Python 绑定不如 Playwright 成熟 | ❌ 淘汰（功能弱于 Playwright） |
| Requests/httpx + BeautifulSoup | 轻量、快 | 无法执行 JS、无法处理 SPA/反爬站点 | ❌ 淘汰（作为辅助，不能作为主力） |
| Tavily / SerpAPI | 托管搜索 API、零运维 | SaaS 依赖、付费、违反本地部署原则 | ❌ 淘汰（SaaS 依赖，仅作为可选模式） |

**决策理由**：Agent 搜索网页资料是"证据诚实性"的基础，必须能应对现代 JS 渲染的网站。Playwright 在自动化能力和反检测之间有最佳平衡。Docker 镜像中在最终运行阶段安装了 Chromium 运行依赖（libglib2.0-0、libnss3 等，注意 AGENTS.md §4.2 踩坑记录）。

参考 [tools/README.md](backend/app/tools/README.md)。

---

## ORM 与数据迁移

**选型：SQLAlchemy 2.0（async）+ Alembic**

| 候选方案 | 优势 | 劣势 | 结论 |
|---|---|---|---|
| **SQLAlchemy 2.0 (async)** | Python 最成熟 ORM、async 原生（2.0 版本）、Unit of Work 模式、 Alembic 迁移、灵活的 raw SQL 混合 | 学习曲线陡、API 复杂 | ✅ 选用 |
| Tortoise ORM | 原生 async、API 类似 Django ORM、上手快 | 生态小、复杂查询弱、Aerich 迁移工具不成熟 | ❌ 淘汰（生态弱） |
| Peewee | 轻量、简单 | async 支持弱、功能简单 | ❌ 淘汰（async 不足） |
| Django ORM | 成熟、强大 | 必须用 Django 框架、async 是后加的 | ❌ 淘汰（框架绑定） |
| 直接 asyncpg + SQL | 最灵活、性能最高 | 需要自己写所有 CRUD、无迁移工具、模型无校验 | ❌ 淘汰（重复造轮子） |

**关键约束**：
- raw SQL 创建的表（如 tenants，由插件管理）**不要**在 ORM 模型中声明 `ForeignKey`（AGENTS.md §4.12 踩坑）
- 模块级 asyncio 原语必须使用 `LazyLock`/`LazySemaphore`（AGENTS.md §4.1）
- 非核心字段走 `meetings.metadata JSONB`（ADR-002）

---

## 测试策略

**选型：pytest + pytest-asyncio + pytest-xdist + Docker Compose 集成测试**

| 维度 | 选型 | 理由 |
|---|---|---|
| 后端单元/集成测试 | pytest + pytest-asyncio | Python 生态标准、async 原生支持 |
| 并行测试 | pytest-xdist | 多核加速，`-n auto` 自动检测，已内置 `_apply_xdist_isolation()` 实现 worker 级数据隔离（独立 PG 库/Redis DB/Qdrant collection） |
| 前端测试 | Vitest + Testing Library | Vite 原生、速度快、与 Vite 配置共享 |
| E2E 测试 | 预留 Playwright（当前未启用） | 前后端都用 Playwright，统一工具链 |
| Stub 模式 | `CONCLAVE_WEB_SEARCH_MODE=stub`、StubLLM、StubEmbedding | 测试不依赖外网、不消耗 API Key |
| CI 环境 | Docker Compose 一键跑 | 与开发环境一致，避免"在我机器上能跑"问题 |

**测试纪律**（参见 AGENTS.md §5.7）：
- 测试禁止依赖外网
- 测试数据自包含
- 清理数据用 `DELETE + ALTER SEQUENCE RESTART` 代替 `TRUNCATE CASCADE`（AGENTS.md §4.10）
- 测试 fixture 必须重置单例（避免跨测试事件循环泄漏）

---

## 代码质量工具

**选型：Ruff（lint + format）+ mypy（类型检查）+ ESLint（前端）**

| 工具 | 选型 | 淘汰理由 |
|---|---|---|
| Python linter/formatter | **Ruff**（同时替代 flake8 + isort + black + pyupgrade）| Ruff 比 flake8 快 100 倍，一个工具覆盖 lint + format + import 排序；black 不再需要 |
| Python 类型检查 | **mypy 2.3.0** | Pyright 也不错但生态和 CI 集成以 mypy 为主；版本锁定避免 CI 漂移 |
| JS/TS linter | **ESLint**（typescript-eslint） | TSLint 已废弃；Biome 虽快但生态不如 ESLint |
| JS/TS 类型检查 | **tsc --noEmit** | 官方工具最准确 |
| Pre-commit | **pre-commit + pre-push 双层 Hook** | 秒级快速检查（ruff/tsc/eslint）+ Docker CI 一致性验证（AGENTS.md §4.18/§4.20） |

**版本一致性原则**（AGENTS.md §4.18）：ruff/mypy 版本在 `requirements.lock`、`.pre-commit-config.yaml`、本地安装三处必须一致，避免"本地通过 CI 红"。

---

## 不选的东西

以下技术被**明确排除**，记录在此避免未来反复讨论：

| 技术/模式 | 不选的理由 |
|---|---|
| 微服务架构 | 当前规模单体足够，服务间通信复杂度 > 收益。以模块化单体（Monolith Modular）+ 插件框架实现扩展性 |
| 消息队列持久化（Kafka/RabbitMQ） | 事件已持久化到 PG，Redis Pub/Sub 只做实时广播，不需要 MQ |
| GraphQL | 前端页面数量有限、数据结构明确，REST + WebSocket 更简单 |
| 服务网格（Istio/Linkerd） | Docker Compose 部署场景下完全不需要 |
| 服务端渲染（SSR/Next.js） | 这是内部工具类 SPA，SEO 无需求，CSR 足够 |
| CSS-in-JS（styled-components/emotion） | 运行时开销、与严格 CSS 变量设计系统冲突；使用纯 CSS + CSS 变量 |
| 状态管理库（Redux/Zustand/Jotai） | 当前状态复杂度用 React Context + useReducer 足够，引入第三方库增加包体积 |
| 任务队列（Celery/ARQ） | 异步任务直接用 asyncio.create_task + 事件总线，不需要独立 worker 进程 |
| GraphQL / tRPC | REST + 自动 OpenAPI 文档已满足前后端联调需求 |
| gRPC（除 Worker 预留） | 主链路 REST + WebSocket 更简单；gRPC 仅用于未来跨语言 Worker 扩展（compute.proto 已预留） |

---

## 选型复盘原则

本文档是活文档。如果未来出现以下情况，应重新评估选型：

1. 规模变化：QPS 增长 10 倍、存储量增长 100 倍 → 可能需要引入 K8s/Kafka
2. 生态变化：某个被淘汰的方案出现突破性进展（如 Chroma 发布生产级版本）
3. 需求变化：增加 SaaS 多租户托管 → 需要重新评估认证/隔离方案
4. 团队变化：新成员对某个方案有深度经验且能证明显著收益

新增选型决策请遵循 ADR 流程：在 `docs/design/adr/` 下创建 ADR 文档，Accepted 后再实施。
