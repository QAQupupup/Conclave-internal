/**
 * Mock data for demo mode
 * When user logs in via "演示模式", all API calls return mock data
 */
import type { Meeting, MeetingMessage, PaginatedResponse, StageId } from '@/types';

// Check if using demo token
export function isDemoMode(): boolean {
  try {
    const token = localStorage.getItem('conclave:auth');
    if (token) {
      const parsed = JSON.parse(token);
      return typeof parsed.state?.token === 'string' && parsed.state.token.startsWith('demo-token-');
    }
  } catch { /* ignore parse error */ }
  return false;
}

// Helper to generate timestamps
function hoursAgo(h: number): number {
  return Date.now() - h * 3600_000;
}

function daysAgo(d: number): number {
  return Date.now() - d * 86400_000;
}

function minsAgo(m: number): number {
  return Date.now() - m * 60_000;
}

/** 演示模式下的报告分段（content/items/headers/rows 按 section.type 二选一或多选） */
interface MockReportSection {
  type: string;
  level?: number;
  content?: string;
  items?: string[];
  headers?: string[];
  rows?: string[][];
  label?: string;
  value?: string;
  sublabel?: string;
}

/** 演示模式下的报告 */
interface MockReport {
  id: string;
  title: string;
  meeting_id: string;
  created_at: string;
  status: string;
  summary: string;
  sections: MockReportSection[];
}

/** 演示模式下的 Docker 主机摘要 */
export interface DockerHostSummary {
  id: string;
  name: string;
  host: string;
  status: string;
  is_default: boolean;
  os: string;
  arch: string;
  cpus: number;
  memory: string;
  docker_version: string;
  containers: { running: number; paused: number; stopped: number };
  images_count: number;
  disk_usage: { total: string; used: string; available: string };
  last_seen?: string;
}

// Mock meetings - expanded to 10 meetings with diverse scenarios
const MOCK_MEETINGS: Meeting[] = [
  {
    id: 'meeting-001',
    title: '微服务架构拆分策略讨论',
    topic: '微服务架构拆分策略讨论',
    status: 'done',
    stage: 'done',
    createdAt: daysAgo(2),
    created_at: new Date(daysAgo(2)).toISOString(),
    updatedAt: hoursAgo(40),
    createdBy: 'admin',
    messageCount: 156,
    message_count: 156,
    agents: [
      { id: 'a1', name: '架构师', role: 'architect', state: 'done' },
      { id: 'a2', name: '研发负责人', role: 'tech_lead', state: 'done' },
      { id: 'a3', name: '运维专家', role: 'sre', state: 'done' },
      { id: 'a4', name: '产品经理', role: 'pm', state: 'done' },
    ],
    summary: '讨论了单体到微服务的拆分策略，建议按业务域限界上下文拆分，优先拆分支付和用户模块。采用 Strangler Fig 模式渐进迁移，预计 3 个月完成第一阶段。',
    metadata: { deliverable_type: 'architecture_decision', complexity: 'high' },
  },
  {
    id: 'meeting-002',
    title: 'RAG 检索增强生成优化方案',
    topic: 'RAG 检索增强生成优化方案',
    status: 'running',
    stage: 'intra_team',
    createdAt: hoursAgo(2),
    created_at: new Date(hoursAgo(2)).toISOString(),
    updatedAt: Date.now(),
    createdBy: 'admin',
    messageCount: 42,
    message_count: 42,
    agents: [
      { id: 'a1', name: '算法工程师', role: 'ml_engineer', state: 'speaking' },
      { id: 'a2', name: '搜索专家', role: 'search_expert', state: 'waiting' },
      { id: 'a3', name: '评估专家', role: 'evaluator', state: 'thinking' },
    ],
    summary: null,
    metadata: { deliverable_type: 'technical_report', complexity: 'medium' },
  },
  {
    id: 'meeting-003',
    title: '2026 Q3 技术债偿还计划',
    topic: '2026 Q3 技术债偿还计划',
    status: 'done',
    stage: 'done',
    createdAt: daysAgo(5),
    created_at: new Date(daysAgo(5)).toISOString(),
    updatedAt: daysAgo(5),
    createdBy: 'admin',
    messageCount: 89,
    message_count: 89,
    agents: [
      { id: 'a1', name: '架构师', role: 'architect', state: 'done' },
      { id: 'a2', name: '研发负责人', role: 'tech_lead', state: 'done' },
    ],
    summary: '确定 Q3 优先偿还 3 项高优先级技术债：1) 数据库索引优化（预计 P95 延迟降低 40%） 2) 日志体系重构（统一结构化日志 + ELK 接入） 3) 测试覆盖率从 45% 提升至 70%。',
    metadata: { deliverable_type: 'plan', priority: 'high' },
  },
  {
    id: 'meeting-004',
    title: '多租户数据隔离方案选型',
    topic: '多租户数据隔离方案选型',
    status: 'done',
    stage: 'done',
    createdAt: daysAgo(1),
    created_at: new Date(daysAgo(1)).toISOString(),
    updatedAt: hoursAgo(12),
    createdBy: 'admin',
    messageCount: 203,
    message_count: 203,
    agents: [
      { id: 'a1', name: '架构师', role: 'architect', state: 'done' },
      { id: 'a2', name: 'DBA', role: 'dba', state: 'done' },
      { id: 'a3', name: '安全专家', role: 'security', state: 'done' },
      { id: 'a4', name: '研发负责人', role: 'tech_lead', state: 'done' },
    ],
    summary: '选择了共享数据库+tenant_id行级隔离方案（方案三），兼顾成本和隔离性。核心表添加 tenant_id 外键，通过中间件自动注入租户过滤条件。预计迁移成本 2 人周。',
    metadata: { deliverable_type: 'architecture_decision', complexity: 'high' },
  },
  {
    id: 'meeting-005',
    title: 'AI Agent 评估体系建设',
    topic: 'AI Agent 评估体系建设',
    status: 'paused',
    stage: 'evidence_check',
    createdAt: hoursAgo(5),
    created_at: new Date(hoursAgo(5)).toISOString(),
    updatedAt: hoursAgo(1),
    createdBy: 'admin',
    messageCount: 67,
    message_count: 67,
    agents: [
      { id: 'a1', name: '算法工程师', role: 'ml_engineer', state: 'paused' },
      { id: 'a2', name: '评估专家', role: 'evaluator', state: 'paused' },
      { id: 'a3', name: '产品经理', role: 'pm', state: 'paused' },
    ],
    summary: null,
    metadata: { deliverable_type: 'evaluation_plan' },
  },
  {
    id: 'meeting-006',
    title: '前端性能优化专项讨论',
    topic: '前端性能优化专项讨论',
    status: 'pending',
    stage: 'pending',
    createdAt: Date.now(),
    created_at: new Date().toISOString(),
    updatedAt: Date.now(),
    createdBy: 'admin',
    messageCount: 0,
    message_count: 0,
    agents: [],
    summary: null,
    metadata: {},
  },
  {
    id: 'meeting-007',
    title: 'Kubernetes 集群扩缩容策略',
    topic: 'Kubernetes 集群扩缩容策略',
    status: 'done',
    stage: 'done',
    createdAt: daysAgo(7),
    created_at: new Date(daysAgo(7)).toISOString(),
    updatedAt: daysAgo(6),
    createdBy: 'admin',
    messageCount: 124,
    message_count: 124,
    agents: [
      { id: 'a1', name: '运维专家', role: 'sre', state: 'done' },
      { id: 'a2', name: '架构师', role: 'architect', state: 'done' },
      { id: 'a3', name: '研发负责人', role: 'tech_lead', state: 'done' },
    ],
    summary: '确定 HPA + VPA 组合策略：CPU > 70% 触发水平扩容，内存不足时垂直扩配。设置 PDB 确保滚动更新时最少 2 副本。引入 KEDA 支持基于消息队列深度的自定义指标扩缩。',
    metadata: { deliverable_type: 'infrastructure_plan' },
  },
  {
    id: 'meeting-008',
    title: 'API 网关安全加固方案',
    topic: 'API 网关安全加固方案',
    status: 'running',
    stage: 'cross_team',
    createdAt: hoursAgo(1),
    created_at: new Date(hoursAgo(1)).toISOString(),
    updatedAt: minsAgo(15),
    createdBy: 'admin',
    messageCount: 38,
    message_count: 38,
    agents: [
      { id: 'a1', name: '安全专家', role: 'security', state: 'speaking' },
      { id: 'a2', name: '架构师', role: 'architect', state: 'thinking' },
      { id: 'a3', name: '运维专家', role: 'sre', state: 'waiting' },
    ],
    summary: null,
    metadata: { deliverable_type: 'security_review' },
  },
  {
    id: 'meeting-009',
    title: '用户反馈系统设计方案',
    topic: '用户反馈系统设计方案',
    status: 'done',
    stage: 'done',
    createdAt: daysAgo(3),
    created_at: new Date(daysAgo(3)).toISOString(),
    updatedAt: daysAgo(2),
    createdBy: 'admin',
    messageCount: 95,
    message_count: 95,
    agents: [
      { id: 'a1', name: '产品经理', role: 'pm', state: 'done' },
      { id: 'a2', name: '架构师', role: 'architect', state: 'done' },
      { id: 'a3', name: '研发负责人', role: 'tech_lead', state: 'done' },
    ],
    summary: '设计三层反馈收集机制：1) 应用内嵌反馈组件（NPS + 文本） 2) 自动化错误上报（Sentry 集成） 3) 定期用户访谈（双周一次）。数据统一汇入分析平台，按优先级自动分类。',
    metadata: { deliverable_type: 'product_spec' },
  },
  {
    id: 'meeting-010',
    title: '数据库备份与灾难恢复演练',
    topic: '数据库备份与灾难恢复演练',
    status: 'paused',
    stage: 'intra_team',
    createdAt: hoursAgo(8),
    created_at: new Date(hoursAgo(8)).toISOString(),
    updatedAt: hoursAgo(3),
    createdBy: 'admin',
    messageCount: 45,
    message_count: 45,
    agents: [
      { id: 'a1', name: 'DBA', role: 'dba', state: 'paused' },
      { id: 'a2', name: '运维专家', role: 'sre', state: 'paused' },
      { id: 'a3', name: '安全专家', role: 'security', state: 'paused' },
    ],
    summary: null,
    metadata: { deliverable_type: 'disaster_recovery_plan' },
  },
];

// Detailed mock messages for multiple meetings
const MOCK_MESSAGES: Record<string, MeetingMessage[]> = {
  // meeting-001: 微服务架构拆分
  'meeting-001': [
    {
      id: 'm1-001',
      meeting_id: 'meeting-001',
      role: 'system',
      agent_id: undefined,
      agent_name: undefined,
      content: '讨论开始：微服务架构拆分策略讨论',
      timestamp: daysAgo(2),
      stage: 'clarification',
      metadata: {},
    },
    {
      id: 'm2-001',
      meeting_id: 'meeting-001',
      role: 'assistant',
      agent_id: 'a1',
      agent_name: '架构师',
      agent_role: 'architect',
      content: '## 当前架构痛点分析\n\n经过对现有单体架构的深入分析，我识别出以下核心问题：\n\n1. **部署耦合**：任何模块修改都需要全量部署，发布频率被限制在每周 1 次\n2. **扩展瓶颈**：用户模块高峰期需要 10 倍资源，但无法独立扩容\n3. **技术栈锁定**：所有模块共用 Spring Boot 2.x，无法引入新技术\n\n建议采用 **Strangler Fig 模式** 渐进式迁移，而非大爆炸式重写。',
      timestamp: daysAgo(2) + 300000,
      stage: 'clarification',
      metadata: { thought: false },
    },
    {
      id: 'm3-001',
      meeting_id: 'meeting-001',
      role: 'assistant',
      agent_id: 'a4',
      agent_name: '产品经理',
      agent_role: 'pm',
      content: '从产品角度看，当前最大的问题是**发布速度影响用户体验**。\n\n- 用户模块需求排期 3 周，但竞品 3 天就能上线新功能\n- 支付模块每次更新都有回归风险，测试成本极高\n\n建议优先拆分**用户模块**和**支付模块**，这两个是业务核心且变更最频繁。',
      timestamp: daysAgo(2) + 600000,
      stage: 'clarification',
      metadata: { thought: false },
    },
    {
      id: 'm4-001',
      meeting_id: 'meeting-001',
      role: 'assistant',
      agent_id: 'a2',
      agent_name: '研发负责人',
      agent_role: 'tech_lead',
      content: '## 拆分优先级评估\n\n| 模块 | 业务价值 | 技术复杂度 | 依赖关系 | 优先级 |\n|------|---------|-----------|---------|--------|\n| 用户服务 | 高 | 低 | 少 | P0 |\n| 支付服务 | 高 | 高 | 中 | P0 |\n| 订单服务 | 高 | 中 | 多 | P1 |\n| 通知服务 | 中 | 低 | 少 | P1 |\n| 报表服务 | 低 | 中 | 多 | P2 |\n\n建议第一阶段（6 周）完成用户+支付拆分。',
      timestamp: daysAgo(2) + 900000,
      stage: 'intra_team',
      metadata: { thought: false },
    },
    {
      id: 'm5-001',
      meeting_id: 'meeting-001',
      role: 'assistant',
      agent_id: 'a3',
      agent_name: '运维专家',
      agent_role: 'sre',
      content: '## 运维侧准备清单\n\n拆分前需要确保以下基础设施就绪：\n\n1. **K8s 集群**：当前 3 节点，需扩到 5 节点支撑微服务部署\n2. **Service Mesh**：部署 Istio 管理服务间通信\n3. **可观测性**：\n   - Prometheus + Grafana（指标监控）\n   - Jaeger（分布式追踪）\n   - ELK（日志聚合）\n4. **CI/CD 流水线**：每个服务独立流水线，预计 Jenkins → GitLab CI 迁移\n\n⚠️ 风险提醒：服务拆分后，故障排查复杂度会显著上升，建议先建好可观测性体系。',
      timestamp: daysAgo(2) + 1200000,
      stage: 'intra_team',
      metadata: { thought: false },
    },
    {
      id: 'm6-001',
      meeting_id: 'meeting-001',
      role: 'tool_call',
      agent_id: 'a1',
      agent_name: '架构师',
      agent_role: 'architect',
      content: '正在检索微服务拆分最佳实践...',
      timestamp: daysAgo(2) + 1500000,
      stage: 'intra_team',
      metadata: {
        tool_name: 'web_search',
        tool_status: 'completed',
        tool_input: { query: 'microservices strangler fig pattern best practices 2026' },
      },
    },
    {
      id: 'm7-001',
      meeting_id: 'meeting-001',
      role: 'assistant',
      agent_id: 'a1',
      agent_name: '架构师',
      agent_role: 'architect',
      content: '## 最终建议\n\n综合讨论结果，建议采用以下拆分策略：\n\n### 第一阶段（6 周）\n- 拆分用户服务（独立数据库 + Redis 缓存）\n- 拆分支付服务（独立数据库 + 幂等性设计）\n- 部署 API Gateway（Kong / APISIX）\n\n### 第二阶段（8 周）\n- 拆分订单服务（Saga 事务管理）\n- 拆分通知服务（事件驱动，Kafka 消费）\n\n### 关键决策\n- **服务间通信**：同步用 gRPC，异步用 Kafka\n- **数据一致性**：Saga 模式 + 最终一致性\n- **灰度发布**：Istio traffic splitting\n\n预计总成本：3 人 × 14 周 = 42 人周',
      timestamp: daysAgo(2) + 1800000,
      stage: 'produce',
      metadata: { thought: false },
    },
  ],

  // meeting-002: RAG 优化（已有详细数据，保持不变）
  'meeting-002': [
    {
      id: 'm1',
      meeting_id: 'meeting-002',
      role: 'system',
      agent_id: undefined,
      agent_name: undefined,
      content: '讨论开始：RAG 检索增强生成优化方案',
      timestamp: hoursAgo(2),
      stage: 'clarification',
      metadata: {},
    },
    {
      id: 'm2',
      meeting_id: 'meeting-002',
      role: 'assistant',
      agent_id: 'a1',
      agent_name: '算法工程师',
      agent_role: 'ml_engineer',
      content: '我建议从三个维度优化 RAG 系统：\n\n1. **检索阶段优化**：\n   - 使用 Hybrid Search（BM25 + Dense Vector）\n   - 引入 Reranker 对召回结果精排\n   - 查询改写（Query Rewriting）处理模糊查询\n\n2. **Chunking 策略优化**：\n   - 语义分块替代固定长度分块\n   - 父子块策略（Parent-Child Chunking）\n   - 元数据增强（标题、章节、摘要）\n\n3. **生成阶段优化**：\n   - 引入 HyDE（Hypothetical Document Embeddings）\n   - 上下文压缩减少噪音\n   - 引用溯源确保答案可验证',
      timestamp: hoursAgo(1.9),
      stage: 'intra_team',
      metadata: { thought: false },
    },
    {
      id: 'm3',
      meeting_id: 'meeting-002',
      role: 'assistant',
      agent_id: 'a2',
      agent_name: '搜索专家',
      agent_role: 'search_expert',
      content: '补充一下检索优化的细节：\n\n**关于 Hybrid Search 的权重分配**：\n- 建议初始 BM25:Dense = 0.3:0.7\n- 根据领域数据特点调整，技术文档 BM25 权重可以提到 0.4\n\n**Reranker 选型建议**：\n- 中文场景推荐 bge-reranker-v2-m3\n- 跨语言场景推荐 Cohere Rerank 3\n- 轻量级场景可用 cross-encoder/ms-marco-MiniLM-L-6-v2\n\n另外，建议添加 **Query Expansion** 步骤，用 LLM 生成 3-5 个相关查询并行检索，能显著提升召回率。',
      timestamp: hoursAgo(1.7),
      stage: 'intra_team',
      metadata: { thought: false },
    },
    {
      id: 'm4',
      meeting_id: 'meeting-002',
      role: 'assistant',
      agent_id: 'a3',
      agent_name: '评估专家',
      agent_role: 'evaluator',
      content: '从评估角度，我建议建立三维评估体系：\n\n| 维度 | 指标 | 目标值 |\n|------|------|--------|\n| 检索质量 | Recall@5, MRR, NDCG@10 | Recall@5 > 0.85 |\n| 生成质量 | 忠实度、相关性、完整性 | 忠实度 > 0.9 |\n| 系统性能 | P50/P95 延迟、QPS | P95 < 3s |\n\n需要准备：\n1. 标注数据集（200+ QA 对）\n2. 自动化评估流水线\n3. A/B 测试框架',
      timestamp: hoursAgo(1.5),
      stage: 'evidence_check',
      metadata: { thought: false },
    },
    {
      id: 'm5',
      meeting_id: 'meeting-002',
      role: 'tool_call',
      agent_id: 'a1',
      agent_name: '算法工程师',
      agent_role: 'ml_engineer',
      content: '正在检索 RAG 优化最佳实践...',
      timestamp: hoursAgo(1.2),
      stage: 'intra_team',
      metadata: {
        tool_name: 'web_search',
        tool_status: 'completed',
        tool_input: { query: 'RAG optimization best practices 2026' },
      },
    },
    {
      id: 'm6',
      meeting_id: 'meeting-002',
      role: 'assistant',
      agent_id: 'a1',
      agent_name: '算法工程师',
      agent_role: 'ml_engineer',
      content: '根据检索结果，补充几个 2026 年的新趋势：\n\n1. **Graph RAG**：利用知识图谱增强检索，特别适合多跳推理问题\n2. **Adaptive RAG**：根据查询复杂度动态选择检索策略\n3. **Self-RAG**：模型自主判断是否需要检索、检索内容是否相关\n4. **RAG Fusion**：多查询生成 + Reciprocal Rank Fusion 排序\n\n我建议先实现基础版（Hybrid + Reranker），上线后再迭代高级特性。',
      timestamp: hoursAgo(1),
      stage: 'intra_team',
      metadata: { thought: false },
    },
  ],

  // meeting-003: Q3 技术债偿还计划
  'meeting-003': [
    {
      id: 'm1-003',
      meeting_id: 'meeting-003',
      role: 'system',
      agent_id: undefined,
      agent_name: undefined,
      content: '讨论开始：2026 Q3 技术债偿还计划',
      timestamp: daysAgo(5),
      stage: 'clarification',
      metadata: {},
    },
    {
      id: 'm2-003',
      meeting_id: 'meeting-003',
      role: 'assistant',
      agent_id: 'a1',
      agent_name: '架构师',
      agent_role: 'architect',
      content: '## 技术债全景扫描\n\n通过 SonarQube 扫描和团队投票，我整理了当前技术债清单：\n\n| 技术债 | 影响范围 | 严重度 | 估算成本 |\n|--------|---------|--------|---------|\n| 数据库缺少复合索引 | 全系统 P95 延迟 > 800ms | 高 | 2 人周 |\n| 日志格式不统一（mix of struct + plain） | 排障效率低 | 高 | 3 人周 |\n| 测试覆盖率仅 45% | 回归风险高 | 高 | 4 人周 |\n| API 文档与实现不一致 | 前端联调效率低 | 中 | 1 人周 |\n| 依赖版本老旧（Spring Boot 2.x → 3.x） | 安全漏洞风险 | 中 | 2 人周 |\n\n建议 Q3 集中火力解决前 3 项 P0 级技术债。',
      timestamp: daysAgo(5) + 300000,
      stage: 'clarification',
      metadata: { thought: false },
    },
    {
      id: 'm3-003',
      meeting_id: 'meeting-003',
      role: 'assistant',
      agent_id: 'a2',
      agent_name: '研发负责人',
      agent_role: 'tech_lead',
      content: '## 研发侧执行计划\n\n**数据库索引优化**（2 人周）：\n1. 用 `pg_stat_statements` 定位慢查询 Top 20\n2. 分析执行计划，添加复合索引\n3. 对高频 JOIN 查询引入覆盖索引（Covering Index）\n4. 预期效果：P95 延迟从 800ms 降至 480ms（-40%）\n\n**日志体系重构**（3 人周）：\n1. 统一使用 `structlog` 输出 JSON 格式日志\n2. 添加 request_id 贯穿全链路\n3. 接入 ELK（Elasticsearch + Logstash + Kibana）\n4. 配置关键错误告警规则\n\n**测试覆盖率提升**（4 人周）：\n1. 核心业务逻辑（DAO/Service）优先补单元测试\n2. API 层补集成测试（Docker Compose 环境）\n3. 目标：核心模块 > 80%，整体 > 70%\n4. CI 卡点：新代码覆盖率 < 80% 禁止合并',
      timestamp: daysAgo(5) + 600000,
      stage: 'intra_team',
      metadata: { thought: false },
    },
    {
      id: 'm4-003',
      meeting_id: 'meeting-003',
      role: 'tool_call',
      agent_id: 'a1',
      agent_name: '架构师',
      agent_role: 'architect',
      content: '正在检索数据库索引优化最佳实践...',
      timestamp: daysAgo(5) + 900000,
      stage: 'intra_team',
      metadata: {
        tool_name: 'web_search',
        tool_status: 'completed',
        tool_input: { query: 'PostgreSQL composite index optimization best practices 2026' },
      },
    },
    {
      id: 'm5-003',
      meeting_id: 'meeting-003',
      role: 'assistant',
      agent_id: 'a1',
      agent_name: '架构师',
      agent_role: 'architect',
      content: '## 资源与排期\n\nQ3 共 13 周，技术债偿还占用：\n\n- 7 月：数据库索引优化（2 人） + 日志重构启动（1 人）\n- 8 月：日志重构收尾（2 人） + 测试覆盖率提升启动（2 人）\n- 9 月：测试覆盖率冲刺（3 人） + 验收 & 回归测试（全员）\n\n**风险缓解**：\n- 每个技术债项指定 Owner，每周 Review 进度\n- 设置阶段性里程碑，避免最后集中赶工\n- 预留 20% buffer 应对紧急线上问题',
      timestamp: daysAgo(5) + 1200000,
      stage: 'produce',
      metadata: { thought: false },
    },
  ],

  // meeting-005: AI Agent 评估体系建设
  'meeting-005': [
    {
      id: 'm1-005',
      meeting_id: 'meeting-005',
      role: 'system',
      agent_id: undefined,
      agent_name: undefined,
      content: '讨论开始：AI Agent 评估体系建设',
      timestamp: hoursAgo(5),
      stage: 'clarification',
      metadata: {},
    },
    {
      id: 'm2-005',
      meeting_id: 'meeting-005',
      role: 'assistant',
      agent_id: 'a1',
      agent_name: '算法工程师',
      agent_role: 'ml_engineer',
      content: '## Agent 评估体系设计思路\n\n当前 Agent 系统缺乏系统性评估，主要问题：\n\n1. **输出质量不可控**：同一输入多次运行结果差异大\n2. **回归难检测**：Prompt 修改后无法量化影响\n3. **缺乏基准线**：无法对比不同模型/Prompt 的效果\n\n建议建立三层评估框架：\n\n| 层级 | 评估内容 | 方法 | 频率 |\n|------|---------|------|------|\n| L1 单元 | 单个 Agent 输出质量 | LLM-as-Judge + 人工抽检 | 每次 Prompt 变更 |\n| L2 集成 | 多 Agent 协作效果 | 端到端场景测试 | 每日 CI |\n| L3 系统 | 整体会议质量 | 用户满意度 + 产出评分 | 每周 |\n\n核心指标：**忠实度 > 0.9，任务完成率 > 85%，幻觉率 < 5%**',
      timestamp: hoursAgo(4.8),
      stage: 'clarification',
      metadata: { thought: false },
    },
    {
      id: 'm3-005',
      meeting_id: 'meeting-005',
      role: 'assistant',
      agent_id: 'a2',
      agent_name: '评估专家',
      agent_role: 'evaluator',
      content: '## 评估数据集与自动化流水线\n\n**标注数据集构建**：\n- 从历史会议中采样 200+ 典型场景\n- 每个场景包含：输入上下文、期望输出、评分标准\n- 按阶段标注：clarification / intra_team / cross_team / produce\n\n**自动化评估流水线**：\n```\nGit Push → CI 触发 → 加载测试集 → 运行 Agent → LLM-as-Judge 评分 → 生成报告\n```\n\n**LLM-as-Judge 设计**：\n- 使用 GPT-4 级别模型做裁判\n- 评分维度：准确性、完整性、相关性、格式规范\n- 每个维度 1-5 分，总分加权平均\n- 与人工评分对齐度目标：Cohen\'s Kappa > 0.75',
      timestamp: hoursAgo(4.5),
      stage: 'intra_team',
      metadata: { thought: false },
    },
    {
      id: 'm4-005',
      meeting_id: 'meeting-005',
      role: 'assistant',
      agent_id: 'a3',
      agent_name: '产品经理',
      agent_role: 'pm',
      content: '从产品角度补充几个关键点：\n\n1. **评估结果可视化**：需要一个 Dashboard 展示趋势\n   - 各 Agent 质量得分趋势\n   - 模型版本对比（A/B 测试结果）\n   - 回归告警（得分下降 > 10% 自动通知）\n\n2. **用户反馈闭环**：\n   - 会议结束后收集用户满意度（1-5 星）\n   - 低分会议自动触发根因分析\n   - 反馈数据反哺评估数据集\n\n3. **成本效益考量**：\n   - LLM-as-Judge 每次评估约 $0.02-0.05\n   - 每日 CI 评估 200 场景 ≈ $4-10/天\n   - 建议初期每周一次全量评估，日常只做冒烟测试',
      timestamp: hoursAgo(4),
      stage: 'evidence_check',
      metadata: { thought: false },
    },
    {
      id: 'm5-005',
      meeting_id: 'meeting-005',
      role: 'tool_call',
      agent_id: 'a1',
      agent_name: '算法工程师',
      agent_role: 'ml_engineer',
      content: '正在检索 Agent 评估框架最新研究...',
      timestamp: hoursAgo(3.5),
      stage: 'evidence_check',
      metadata: {
        tool_name: 'web_search',
        tool_status: 'completed',
        tool_input: { query: 'LLM agent evaluation framework benchmark 2026' },
      },
    },
    {
      id: 'm6-005',
      meeting_id: 'meeting-005',
      role: 'assistant',
      agent_id: 'a1',
      agent_name: '算法工程师',
      agent_role: 'ml_engineer',
      content: '## 实施路线图\n\n根据讨论共识，建议分阶段推进：\n\n**Phase 1（2 周）：基础框架**\n- 搭建评估数据集（首批 50 场景）\n- 实现 LLM-as-Judge 评分器\n- CI 集成冒烟测试（10 核心场景）\n\n**Phase 2（3 周）：自动化流水线**\n- 扩展数据集至 200+ 场景\n- 实现评估 Dashboard\n- 添加回归检测与告警\n\n**Phase 3（持续）：闭环优化**\n- 用户反馈集成\n- A/B 测试框架\n- 评估模型持续校准\n\n⏸️ 当前暂停原因：等待评估数据集标注完成，预计下周恢复讨论。',
      timestamp: hoursAgo(3),
      stage: 'evidence_check',
      metadata: { thought: false },
    },
  ],

  // meeting-004: 多租户数据隔离
  'meeting-004': [
    {
      id: 'm1-004',
      meeting_id: 'meeting-004',
      role: 'system',
      agent_id: undefined,
      agent_name: undefined,
      content: '讨论开始：多租户数据隔离方案选型',
      timestamp: daysAgo(1),
      stage: 'clarification',
      metadata: {},
    },
    {
      id: 'm2-004',
      meeting_id: 'meeting-004',
      role: 'assistant',
      agent_id: 'a1',
      agent_name: '架构师',
      agent_role: 'architect',
      content: '## 三种主流多租户隔离方案\n\n| 方案 | 架构 | 优点 | 缺点 |\n|------|------|------|------|\n| 方案一 | 独立数据库 | 最强隔离、独立备份 | 成本高、运维复杂 |\n| 方案二 | 独立 Schema | 中等隔离、逻辑清晰 | 连接池管理复杂 |\n| 方案三 | 行级隔离 | 成本低、扩展性好 | 需严格中间件保障 |\n\n从 SaaS 产品定位看，我们客户以中小企业为主，建议重点评估**方案三**。',
      timestamp: daysAgo(1) + 300000,
      stage: 'clarification',
      metadata: { thought: false },
    },
    {
      id: 'm3-004',
      meeting_id: 'meeting-004',
      role: 'assistant',
      agent_id: 'a2',
      agent_name: 'DBA',
      agent_role: 'dba',
      content: '## DBA 视角的方案评估\n\n**方案三（行级隔离）的关键风险**：\n1. 数据泄露风险：任何 SQL 漏加 tenant_id 条件都会跨租户\n2. 性能热点：大租户数据量膨胀影响其他租户\n3. 备份恢复：无法按租户单独备份\n\n**缓解措施**：\n- 中间件层自动注入 `WHERE tenant_id = ?`（MyBatis Interceptor / SQLAlchemy Event）\n- 按 tenant_id 分区（Partition），大租户可独立表空间\n- 逻辑备份支持按 tenant_id 过滤导出\n\n建议添加**租户数据量监控**，超过阈值自动告警。',
      timestamp: daysAgo(1) + 600000,
      stage: 'intra_team',
      metadata: { thought: false },
    },
    {
      id: 'm4-004',
      meeting_id: 'meeting-004',
      role: 'assistant',
      agent_id: 'a3',
      agent_name: '安全专家',
      agent_role: 'security',
      content: '## 安全审计意见\n\n行级隔离方案需要以下安全控制：\n\n1. **强制中间件**：所有数据库访问必须经过租户过滤中间件，禁止直连\n2. **审计日志**：记录所有跨租户访问尝试（即使是 bug 导致的）\n3. **渗透测试**：上线前进行专项租户隔离测试\n4. **权限最小化**：应用账号只有 CRUD 权限，无 DDL 权限\n\n⚠️ 合规要求：如果未来有企业客户需要独立部署，方案三需要能平滑升级到方案一。',
      timestamp: daysAgo(1) + 900000,
      stage: 'cross_team',
      metadata: { thought: false },
    },
    {
      id: 'm5-004',
      meeting_id: 'meeting-004',
      role: 'assistant',
      agent_id: 'a4',
      agent_name: '研发负责人',
      agent_role: 'tech_lead',
      content: '## 实施计划\n\n建议分三步实施：\n\n**第一步（1 周）：基础设施**\n- 创建 tenants 表 + users.tenant_id 外键\n- 实现 TenantContext（ThreadLocal/ContextVar）\n- 编写 SQLAlchemy 事件自动注入 tenant_id\n\n**第二步（1 周）：数据迁移**\n- 现有数据标记为 tenant_id=1（默认租户）\n- 编写迁移脚本，支持回滚\n\n**第三步（验证）**\n- 自动化测试覆盖所有 DAO 的租户隔离\n- 渗透测试验证无跨租户访问\n\n总成本估算：2 人周',
      timestamp: daysAgo(1) + 1200000,
      stage: 'produce',
      metadata: { thought: false },
    },
  ],

  // meeting-008: API 网关安全加固（进行中）
  'meeting-008': [
    {
      id: 'm1-008',
      meeting_id: 'meeting-008',
      role: 'system',
      agent_id: undefined,
      agent_name: undefined,
      content: '讨论开始：API 网关安全加固方案',
      timestamp: hoursAgo(1),
      stage: 'clarification',
      metadata: {},
    },
    {
      id: 'm2-008',
      meeting_id: 'meeting-008',
      role: 'assistant',
      agent_id: 'a1',
      agent_name: '安全专家',
      agent_role: 'security',
      content: '## 当前安全风险评估\n\n经过近期渗透测试，发现以下问题：\n\n1. **JWT 未绑定受众**：access_token 可跨 API 使用\n2. **缺少速率限制**：登录接口可被暴力破解\n3. **CORS 配置过宽**：`Access-Control-Allow-Origin: *`\n4. **敏感信息泄露**：错误响应包含堆栈信息\n\n建议优先级：\n- P0：JWT iss/aud 声明 + 速率限制\n- P1：CORS 收紧 + 错误响应脱敏\n- P2：请求签名 + IP 黑名单',
      timestamp: hoursAgo(0.9),
      stage: 'clarification',
      metadata: { thought: false },
    },
    {
      id: 'm3-008',
      meeting_id: 'meeting-008',
      role: 'assistant',
      agent_id: 'a2',
      agent_name: '架构师',
      agent_role: 'architect',
      content: '同意安全专家的分析。补充架构层面的建议：\n\n**JWT 加固方案**：\n```json\n{\n  "iss": "conclave-backend",\n  "aud": "conclave-api",\n  "jti": "<uuid>",\n  "exp": 1234567890\n}\n```\n\n**速率限制策略**：\n- 登录：5 次/分钟/IP\n- API 调用：100 次/分钟/用户\n- 使用 Redis 滑动窗口计数\n\n**CORS 配置**：\n- 生产环境只允许 `*.conclave.io` 域名\n- 开发环境允许 `localhost:*`',
      timestamp: hoursAgo(0.7),
      stage: 'cross_team',
      metadata: { thought: false },
    },
  ],

  // meeting-007: Kubernetes 集群扩缩容策略
  'meeting-007': [
    {
      id: 'm1-007',
      meeting_id: 'meeting-007',
      role: 'system',
      agent_id: undefined,
      agent_name: undefined,
      content: '讨论开始：Kubernetes 集群扩缩容策略',
      timestamp: daysAgo(7),
      stage: 'clarification',
      metadata: {},
    },
    {
      id: 'm2-007',
      meeting_id: 'meeting-007',
      role: 'assistant',
      agent_id: 'a1',
      agent_name: '运维专家',
      agent_role: 'sre',
      content: '## 当前集群现状分析\n\n**集群配置**：\n- 3 个 Worker 节点（8C32G  each）\n- 运行 23 个 Pod，平均 CPU 利用率 45%\n- 高峰期（10:00-12:00）CPU 飙升至 85%+\n\n**核心问题**：\n1. 固定副本数导致资源浪费（夜间利用率 < 20%）\n2. 突发流量时手动扩容响应慢（需 15-30 分钟）\n3. 内存密集型服务（算法推理）频繁 OOMKilled\n\n建议引入 **HPA + VPA + KEDA** 三层扩缩容体系。',
      timestamp: daysAgo(7) + 300000,
      stage: 'clarification',
      metadata: { thought: false },
    },
    {
      id: 'm3-007',
      meeting_id: 'meeting-007',
      role: 'assistant',
      agent_id: 'a2',
      agent_name: '架构师',
      agent_role: 'architect',
      content: '## 扩缩容架构设计\n\n**HPA（Horizontal Pod Autoscaler）**：\n- CPU > 70% 触发扩容，< 30% 触发缩容\n- 最小 2 副本，最大 10 副本\n- 冷却期：扩容 60s，缩容 300s（防抖动）\n\n**VPA（Vertical Pod Autoscaler）**：\n- 内存不足时自动调整 requests/limits\n- 仅对非关键服务启用 Auto 模式\n- 核心服务用 Off 模式（仅推荐，不自动执行）\n\n**KEDA（Kubernetes Event-Driven Autoscaling）**：\n- 基于 Kafka 消费队列深度扩缩\n- 基于 Redis 列表长度扩缩\n- 支持缩容到 0（节省夜间成本）\n\n**PDB（Pod Disruption Budget）**：\n- 滚动更新时最少保持 2 副本\n- `minAvailable: 2` 或 `maxUnavailable: 1`',
      timestamp: daysAgo(7) + 600000,
      stage: 'intra_team',
      metadata: { thought: false },
    },
    {
      id: 'm4-007',
      meeting_id: 'meeting-007',
      role: 'assistant',
      agent_id: 'a3',
      agent_name: '研发负责人',
      agent_role: 'tech_lead',
      content: '## 研发侧配合事项\n\n1. **服务无状态化**：确保所有服务支持水平扩展\n   - Session 统一存 Redis\n   - 文件上传走 OSS，不存本地\n   - 定时任务用分布式锁防重复执行\n\n2. **优雅启停**：\n   - 实现 `preStop` hook（sleep 10s 等待流量切换）\n   - 处理 SIGTERM 信号，完成在途请求\n   - 健康检查：`/healthz`（存活）+ `/readyz`（就绪）\n\n3. **资源配额建议**：\n\n| 服务类型 | CPU Request | CPU Limit | Mem Request | Mem Limit |\n|---------|-------------|-----------|-------------|----------|\n| API 网关 | 200m | 1000m | 256Mi | 512Mi |\n| 业务服务 | 300m | 1500m | 512Mi | 1Gi |\n| 算法推理 | 1000m | 4000m | 2Gi | 4Gi |\n| 后台任务 | 100m | 500m | 128Mi | 256Mi |',
      timestamp: daysAgo(7) + 900000,
      stage: 'cross_team',
      metadata: { thought: false },
    },
    {
      id: 'm5-007',
      meeting_id: 'meeting-007',
      role: 'tool_call',
      agent_id: 'a1',
      agent_name: '运维专家',
      agent_role: 'sre',
      content: '正在检索 KEDA 自定义指标扩缩最佳实践...',
      timestamp: daysAgo(7) + 1200000,
      stage: 'intra_team',
      metadata: {
        tool_name: 'web_search',
        tool_status: 'completed',
        tool_input: { query: 'KEDA custom metrics autoscaling Kafka consumer 2026' },
      },
    },
    {
      id: 'm6-007',
      meeting_id: 'meeting-007',
      role: 'assistant',
      agent_id: 'a1',
      agent_name: '运维专家',
      agent_role: 'sre',
      content: '## 成本与收益分析\n\n**当前成本**（固定 5 节点）：\n- 月度费用：约 ¥18,000\n- 资源利用率：日均 45%，夜间低至 15%\n\n**优化后预估**（弹性 3-7 节点）：\n- 月度费用：约 ¥12,000（节省 ~35%）\n- 夜间自动缩至 3 节点\n- 高峰期自动扩至 7 节点\n- 预计全年节省：¥72,000\n\n**实施计划**：\n1. 第 1 周：部署 HPA + PDB，验证水平扩缩\n2. 第 2 周：部署 VPA，验证垂直扩配\n3. 第 3 周：部署 KEDA，接入 Kafka 指标\n4. 第 4 周：压测验证 + 成本核算',
      timestamp: daysAgo(6),
      stage: 'produce',
      metadata: { thought: false },
    },
  ],

  // meeting-009: 用户反馈系统设计方案
  'meeting-009': [
    {
      id: 'm1-009',
      meeting_id: 'meeting-009',
      role: 'system',
      agent_id: undefined,
      agent_name: undefined,
      content: '讨论开始：用户反馈系统设计方案',
      timestamp: daysAgo(3),
      stage: 'clarification',
      metadata: {},
    },
    {
      id: 'm2-009',
      meeting_id: 'meeting-009',
      role: 'assistant',
      agent_id: 'a1',
      agent_name: '产品经理',
      agent_role: 'pm',
      content: '## 用户反馈系统需求分析\n\n当前反馈收集痛点：\n1. 反馈渠道分散（邮件、微信群、口头）无法统一管理\n2. 错误信息不完整，复现困难\n3. 缺乏优先级分类，重要反馈被淹没\n\n**目标**：建立三层反馈收集机制\n\n| 层级 | 渠道 | 自动化程度 | 目标 |\n|------|------|-----------|------|\n| L1 | 应用内嵌反馈组件 | 半自动 | 主动收集 NPS + 文本反馈 |\n| L2 | Sentry 错误上报 | 全自动 | 自动捕获前端异常 + 后端错误 |\n| L3 | 定期用户访谈 | 手动 | 深度理解用户需求与痛点 |\n\n数据统一汇入分析平台，按优先级自动分类。',
      timestamp: daysAgo(3) + 300000,
      stage: 'clarification',
      metadata: { thought: false },
    },
    {
      id: 'm3-009',
      meeting_id: 'meeting-009',
      role: 'assistant',
      agent_id: 'a2',
      agent_name: '架构师',
      agent_role: 'architect',
      content: '## 技术架构设计\n\n**反馈组件（前端）**：\n- 嵌入式 Widget（右下角浮动按钮）\n- 支持 NPS 评分（0-10）+ 文本描述 + 截图上传\n- 自动附带上下文：当前页面 URL、用户操作路径、浏览器信息\n- 组件大小 < 15KB gzipped，不影响页面性能\n\n**Sentry 集成（全栈）**：\n- 前端：`@sentry/react` 捕获 React Error Boundary + 未处理异常\n- 后端：`sentry-python` 捕获未处理异常 + 日志级别上报\n- 自定义 Context：附加 user_id、tenant_id、meeting_id\n- 告警规则：P0 错误 5 分钟内通知，P1 错误 1 小时内通知\n\n**数据分析平台**：\n- 反馈数据写入 PostgreSQL `feedback` 表\n- 文本反馈通过 LLM 自动分类（Bug/功能请求/体验优化/其他）\n- 按严重程度自动分配优先级（P0-P3）\n- Dashboard 展示反馈趋势、分类分布、处理进度',
      timestamp: daysAgo(3) + 600000,
      stage: 'intra_team',
      metadata: { thought: false },
    },
    {
      id: 'm4-009',
      meeting_id: 'meeting-009',
      role: 'assistant',
      agent_id: 'a3',
      agent_name: '研发负责人',
      agent_role: 'tech_lead',
      content: '## 数据模型与 API 设计\n\n**feedback 表结构**：\n```sql\nCREATE TABLE feedback (\n  id UUID PRIMARY KEY,\n  tenant_id UUID NOT NULL,\n  user_id UUID,\n  type VARCHAR(20),       -- nps / bug / feature / ux\n  priority VARCHAR(5),    -- P0 / P1 / P2 / P3\n  content TEXT NOT NULL,\n  context JSONB,          -- 页面 URL、操作路径、浏览器信息\n  screenshot_url TEXT,\n  status VARCHAR(20),     -- new / triaged / in_progress / resolved\n  assignee_id UUID,\n  created_at TIMESTAMPTZ DEFAULT NOW(),\n  updated_at TIMESTAMPTZ DEFAULT NOW()\n);\n```\n\n**API 端点**：\n- `POST /api/feedback` — 提交反馈（匿名也可用）\n- `GET /api/feedback` — 管理后台查看反馈列表\n- `PATCH /api/feedback/:id` — 更新状态/分配处理人\n- `GET /api/feedback/stats` — 统计数据（NPS 趋势、分类分布）',
      timestamp: daysAgo(3) + 900000,
      stage: 'cross_team',
      metadata: { thought: false },
    },
    {
      id: 'm5-009',
      meeting_id: 'meeting-009',
      role: 'assistant',
      agent_id: 'a1',
      agent_name: '产品经理',
      agent_role: 'pm',
      content: '## 用户访谈计划\n\n双周一次，每次 3-5 名用户：\n\n**招募方式**：\n- 从活跃用户中随机抽取\n- 近期提交过反馈的用户优先\n- 新注册用户（使用 < 7 天）单独一组\n\n**访谈结构**（30 分钟/人）：\n1. 热身（5 min）：使用场景、频率\n2. 核心任务（10 min）：观察完成关键任务的过程\n3. 痛点挖掘（10 min）：最不满意的地方、期望改进\n4. 总结（5 min）：NPS 评分 + 开放建议\n\n**输出**：\n- 每次访谈生成结构化纪要\n- 提炼 Top 3 痛点\n- 与反馈数据交叉验证\n- 纳入双周迭代排期',
      timestamp: daysAgo(2.5),
      stage: 'produce',
      metadata: { thought: false },
    },
  ],

  // meeting-010: 数据库备份与灾难恢复演练
  'meeting-010': [
    {
      id: 'm1-010',
      meeting_id: 'meeting-010',
      role: 'system',
      agent_id: undefined,
      agent_name: undefined,
      content: '讨论开始：数据库备份与灾难恢复演练',
      timestamp: hoursAgo(8),
      stage: 'clarification',
      metadata: {},
    },
    {
      id: 'm2-010',
      meeting_id: 'meeting-010',
      role: 'assistant',
      agent_id: 'a1',
      agent_name: 'DBA',
      agent_role: 'dba',
      content: '## 当前备份现状评估\n\n**现有配置**：\n- 每日全量备份（pg_dump），凌晨 2:00 执行\n- 备份保留 7 天\n- 备份存储：本地磁盘 + 每日同步到 OSS\n\n**发现的问题**：\n1. **RPO 过大**：最多丢失 24 小时数据\n2. **未验证恢复**：从未做过恢复演练，不确定备份可用性\n3. **缺少 WAL 归档**：无法做 Point-in-Time Recovery（PITR）\n4. **单点风险**：主库故障时无自动切换\n\n**目标 RPO/RTO**：\n- RPO（恢复点目标）：< 5 分钟\n- RTO（恢复时间目标）：< 30 分钟',
      timestamp: hoursAgo(7.8),
      stage: 'clarification',
      metadata: { thought: false },
    },
    {
      id: 'm3-010',
      meeting_id: 'meeting-010',
      role: 'assistant',
      agent_id: 'a2',
      agent_name: '运维专家',
      agent_role: 'sre',
      content: '## 灾难恢复方案设计\n\n**方案一：PostgreSQL 流复制 + 自动故障切换**\n- 部署 1 主 1 从流复制集群\n- 使用 Patroni 实现自动故障切换（RTO < 30s）\n- 从库可读（分担查询负载）\n\n**方案二：WAL 归档 + PITR**\n- 开启 `archive_mode = on`\n- WAL 文件每 5 分钟归档到 OSS\n- 支持恢复到任意时间点（RPO < 5 min）\n- 恢复流程：恢复最近全量备份 → 回放 WAL 到目标时间点\n\n**方案三：混合方案（推荐）**\n- 流复制保障高可用（自动切换）\n- WAL 归档保障数据恢复（PITR）\n- 每日全量备份作为兜底\n\n**备份验证**：\n- 每周自动恢复测试（恢复到临时实例）\n- 验证数据完整性（行数对比 + checksum）\n- 生成恢复报告',
      timestamp: hoursAgo(7.5),
      stage: 'intra_team',
      metadata: { thought: false },
    },
    {
      id: 'm4-010',
      meeting_id: 'meeting-010',
      role: 'assistant',
      agent_id: 'a3',
      agent_name: '安全专家',
      agent_role: 'security',
      content: '## 安全与合规要求\n\n1. **备份加密**：\n   - 备份文件使用 AES-256 加密\n   - 加密密钥通过 KMS 管理，定期轮换\n   - 传输过程 TLS 加密\n\n2. **访问控制**：\n   - 备份存储桶仅 DBA 角色可访问\n   - 恢复操作需要二次审批\n   - 所有备份/恢复操作记录审计日志\n\n3. **合规要求**：\n   - 数据保留策略：备份保留 90 天\n   - 跨区域备份（满足灾备要求）\n   - 定期渗透测试验证备份系统安全性\n\n⚠️ 注意：恢复演练必须在隔离环境执行，禁止在生产网络内测试。',
      timestamp: hoursAgo(7),
      stage: 'cross_team',
      metadata: { thought: false },
    },
    {
      id: 'm5-010',
      meeting_id: 'meeting-010',
      role: 'tool_call',
      agent_id: 'a2',
      agent_name: '运维专家',
      agent_role: 'sre',
      content: '正在检索 Patroni 高可用部署最佳实践...',
      timestamp: hoursAgo(6),
      stage: 'intra_team',
      metadata: {
        tool_name: 'web_search',
        tool_status: 'completed',
        tool_input: { query: 'Patroni PostgreSQL HA cluster setup best practices 2026' },
      },
    },
    {
      id: 'm6-010',
      meeting_id: 'meeting-010',
      role: 'assistant',
      agent_id: 'a1',
      agent_name: 'DBA',
      agent_role: 'dba',
      content: '## 演练计划与时间表\n\n**第一次演练（本周）**：\n- 场景：模拟主库宕机\n- 验证：Patroni 自动切换到从库\n- 预期 RTO：< 30 秒\n- 验证应用连接自动重连\n\n**第二次演练（下周）**：\n- 场景：模拟数据误删（DROP TABLE）\n- 验证：PITR 恢复到误操作前 1 分钟\n- 预期 RPO：< 5 分钟\n- 验证恢复后数据完整性\n\n**第三次演练（第三周）**：\n- 场景：模拟整个数据中心不可用\n- 验证：从 OSS 备份恢复到新环境\n- 预期 RTO：< 2 小时\n- 验证跨区域恢复能力\n\n⏸️ 当前暂停原因：等待 Patroni 集群部署完成，预计 3 天后恢复。',
      timestamp: hoursAgo(5),
      stage: 'intra_team',
      metadata: { thought: false },
    },
  ],
};

// Enhanced generic mock messages for any meeting
function generateGenericMessages(meetingId: string, meeting: Meeting): MeetingMessage[] {
  const createdAt = meeting.createdAt || Date.now();
  const msgs: MeetingMessage[] = [
    {
      id: `${meetingId}-sys`,
      meeting_id: meetingId,
      role: 'system',
      agent_id: undefined,
      agent_name: undefined,
      content: `讨论开始：${meeting.title}`,
      timestamp: createdAt,
      stage: 'clarification',
      metadata: {},
    },
  ];

  const agentNames = meeting.agents?.map((a) => a.name) || ['主持人', '专家A', '专家B'];
  const roles = meeting.agents?.map((a) => a.role) || ['moderator', 'architect', 'engineer'];

  // Generate more realistic messages based on stage
  const stageContents: Record<StageId, string[]> = {
    clarify: [
      '让我先梳理一下这个议题的核心问题和约束条件。',
      '从我的专业角度来看，这个议题涉及几个关键维度需要分析。',
      '在深入讨论前，我们需要明确几个前提假设。',
    ],
    clarification: [
      '让我先梳理一下这个议题的核心问题和约束条件。',
      '从我的专业角度来看，这个议题涉及几个关键维度需要分析。',
      '在深入讨论前，我们需要明确几个前提假设。',
    ],
    intra_team: [
      '基于初步分析，我建议从以下几个方面入手：\n\n1. 首先评估现有方案的可行性\n2. 对比业界最佳实践\n3. 结合我们的实际情况做适配',
      '我同意这个方向。补充一些技术细节：\n\n- 需要考虑向后兼容性\n- 性能指标需要量化\n- 建议先做 POC 验证',
      '从实施角度看，这个方案的主要挑战在于：\n\n1. 现有系统的迁移成本\n2. 团队学习曲线\n3. 短期内的双重维护开销',
    ],
    cross_team: [
      '我们团队对这个方案有一些顾虑：\n\n- 与我们的现有架构存在冲突\n- 需要协调多个团队的排期\n- 建议增加一个过渡期',
      '理解你们的顾虑。我们可以这样协调：\n\n1. 第一阶段保持兼容\n2. 第二阶段逐步迁移\n3. 提供迁移工具和文档',
    ],
    evidence_check: [
      '我验证了相关数据，结果如下：\n\n| 指标 | 当前值 | 目标值 | 差距 |\n|------|--------|--------|------|\n| 性能 | 基准 | +30% | 需优化 |\n| 成本 | 基准 | -20% | 可实现 |\n\n结论：方案可行，但需要关注性能优化。',
    ],
    arbitrate: [
      '综合各方意见，建议采取折中方案：\n\n1. 核心逻辑按方案 A 实施\n2. 边缘场景按方案 B 处理\n3. 设置 3 个月的评估期',
    ],
    produce: [
      '## 最终交付物\n\n基于以上讨论，我们达成以下共识：\n\n1. **核心决策**：采用推荐方案\n2. **实施计划**：分 3 个阶段，预计 6 周\n3. **风险缓解**：已识别 3 个主要风险并制定应对策略\n4. **成功标准**：定义了 5 个可量化的验收指标',
    ],
    pending: ['等待讨论开始...'],
    done: ['讨论已完成。'],
    paused: ['讨论已暂停。'],
    aborted: ['讨论已中止。'],
    error: ['发生错误。'],
  };

  const stages: StageId[] = ['clarification', 'intra_team', 'cross_team', 'evidence_check', 'produce'];
  const totalMessages = Math.min(meeting.messageCount || meeting.message_count || 10, 15);

  for (let i = 0; i < totalMessages; i++) {
    const agentIdx = i % agentNames.length;
    const stageIdx = Math.min(Math.floor(i / 3), stages.length - 1);
    const stage = stages[stageIdx];
    const contents = stageContents[stage] || stageContents.intra_team;
    const contentIdx = i % contents.length;

    msgs.push({
      id: `${meetingId}-m${i}`,
      meeting_id: meetingId,
      role: 'assistant',
      agent_id: `a${agentIdx}`,
      agent_name: agentNames[agentIdx],
      agent_role: roles[agentIdx],
      content: contents[contentIdx],
      timestamp: createdAt + i * 120000,
      stage: stage,
      metadata: { thought: false },
    });
  }

  return msgs;
}

// Mock API handlers
export const mockApi = {
  getMeetings(params: { page?: number; pageSize?: number; page_size?: number; status?: string; limit?: number }): PaginatedResponse<Meeting> & { concurrent_limit?: number; running_count?: number } {
    let filtered = [...MOCK_MEETINGS];
    if (params.status) {
      filtered = filtered.filter((m) => m.status === params.status);
    }
    const page = params.page || 1;
    const pageSize = params.pageSize || params.page_size || params.limit || 20;
    const start = (page - 1) * pageSize;
    const items = filtered.slice(start, start + pageSize);
    // running_count 口径与后端一致（只统计 running，paused 已释放并发槽位）
    const runningCount = MOCK_MEETINGS.filter((m) => m.status === 'running').length;
    return {
      items,
      total: filtered.length,
      page,
      pageSize,
      page_size: pageSize,
      totalPages: Math.ceil(filtered.length / pageSize),
      total_pages: Math.ceil(filtered.length / pageSize),
      hasMore: start + pageSize < filtered.length,
      // 与后端 MAX_CONCURRENT_MEETINGS 默认值对齐
      concurrent_limit: 5,
      running_count: runningCount,
    };
  },

  getMeeting(id: string): Meeting | null {
    return MOCK_MEETINGS.find((m) => m.id === id) || MOCK_MEETINGS[0];
  },

  getMeetingMessages(id: string, _params?: { before?: number; limit?: number }): { messages: MeetingMessage[] } {
    if (MOCK_MESSAGES[id]) {
      return { messages: MOCK_MESSAGES[id] };
    }
    const meeting = MOCK_MEETINGS.find((m) => m.id === id);
    if (meeting) {
      return { messages: generateGenericMessages(id, meeting) };
    }
    return { messages: [] };
  },

  createMeeting(data: { topic: string; agents?: string[] }): { meeting_id: string } {
    const newId = `meeting-${Date.now()}`;
    const newMeeting: Meeting = {
      id: newId,
      title: data.topic,
      topic: data.topic,
      status: 'pending',
      stage: 'pending',
      createdAt: Date.now(),
      created_at: new Date().toISOString(),
      updatedAt: Date.now(),
      createdBy: 'admin',
      messageCount: 0,
      message_count: 0,
      agents: [],
      summary: null,
      metadata: {},
    };
    MOCK_MEETINGS.unshift(newMeeting);
    return { meeting_id: newId };
  },

  deleteMeeting(_id: string): { success: boolean } {
    return { success: true };
  },

  controlMeeting(_id: string, _signal: string, _payload?: Record<string, unknown>): { success: boolean } {
    return { success: true };
  },

  getAgents(): { roles: Record<string, unknown>[]; total: number } {
    const roles = [
      { id: 'moderator', display_name: '主持人', perspective: '引导讨论方向，确保各方观点得到充分表达', expertise_domains: ['会议主持', '决策 facilitation'], risk_appetite: 'balanced', default_stance: 'neutral', evidence_preference: 'balanced', model_override: '', background_brief: '负责引导会议流程', prompt_template: '', is_builtin: true, is_active: true, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
      { id: 'product_architect', display_name: '产品架构师', perspective: '从产品架构角度审视方案可行性', expertise_domains: ['系统架构', '技术选型', '架构评审'], risk_appetite: 'balanced', default_stance: '', evidence_preference: 'balanced', model_override: '', background_brief: '系统架构设计和技术选型', prompt_template: '', is_builtin: true, is_active: true, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
      { id: 'engineer', display_name: '工程师', perspective: '关注工程实现细节和技术可行性', expertise_domains: ['研发流程', '代码质量', '工程实践'], risk_appetite: 'cautious', default_stance: '', evidence_preference: 'data_driven', model_override: '', background_brief: '研发流程和代码质量', prompt_template: '', is_builtin: true, is_active: true, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
      { id: 'security_expert', display_name: '安全专家', perspective: '从安全合规角度评估风险', expertise_domains: ['安全审计', '渗透测试', '合规检查'], risk_appetite: 'cautious', default_stance: '', evidence_preference: 'data_driven', model_override: '', background_brief: '安全审计和漏洞修复', prompt_template: '', is_builtin: true, is_active: true, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
      { id: 'ux_designer', display_name: 'UX设计师', perspective: '关注用户体验和交互设计', expertise_domains: ['用户体验', '交互设计', '用户研究'], risk_appetite: 'balanced', default_stance: '', evidence_preference: 'balanced', model_override: '', background_brief: '用户体验设计', prompt_template: '', is_builtin: true, is_active: true, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
      { id: 'data_engineer', display_name: '数据工程师', perspective: '从数据角度评估方案合理性', expertise_domains: ['数据库设计', 'SQL优化', '数据迁移'], risk_appetite: 'balanced', default_stance: '', evidence_preference: 'data_driven', model_override: '', background_brief: '数据库设计和优化', prompt_template: '', is_builtin: true, is_active: true, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
      { id: 'ml_engineer', display_name: '算法工程师', perspective: '从算法和模型角度提供专业意见', expertise_domains: ['机器学习', 'NLP', '推荐算法'], risk_appetite: 'adventurous', default_stance: '', evidence_preference: 'data_driven', model_override: '', background_brief: '机器学习和模型优化', prompt_template: '', is_builtin: false, is_active: true, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
      { id: 'sre', display_name: '运维专家', perspective: '关注系统稳定性和可运维性', expertise_domains: ['部署运维', '监控告警', '容灾备份'], risk_appetite: 'cautious', default_stance: '', evidence_preference: 'data_driven', model_override: '', background_brief: '部署运维和性能调优', prompt_template: '', is_builtin: false, is_active: true, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
    ];
    return { roles, total: roles.length };
  },

  getGraphData(_meetingId?: string): Record<string, unknown> {
    return {
      nodes: [
        { id: 't1', type: 'topic', label: 'RAG 优化', x: 400, y: 100, vx: 0, vy: 0, weight: 10 },
        { id: 'c1', type: 'claim', label: 'Hybrid Search 提升召回率', x: 200, y: 250, vx: 0, vy: 0, weight: 8 },
        { id: 'c2', type: 'claim', label: 'Reranker 显著提升精度', x: 400, y: 250, vx: 0, vy: 0, weight: 7 },
        { id: 'c3', type: 'claim', label: 'Chunking 策略影响大', x: 600, y: 250, vx: 0, vy: 0, weight: 6 },
        { id: 'e1', type: 'evidence', label: 'BM25+Dense 实验: Recall+23%', x: 150, y: 400, vx: 0, vy: 0, weight: 5 },
        { id: 'e2', type: 'evidence', label: 'bge-reranker 评测: NDCG+15%', x: 350, y: 400, vx: 0, vy: 0, weight: 5 },
        { id: 'e3', type: 'evidence', label: '语义分块对比: 准确率+18%', x: 550, y: 400, vx: 0, vy: 0, weight: 4 },
        { id: 's1', type: 'source', label: 'arXiv:2312.06648', x: 150, y: 520, vx: 0, vy: 0, weight: 3 },
        { id: 's2', type: 'source', label: 'BGE 技术报告', x: 350, y: 520, vx: 0, vy: 0, weight: 3 },
        { id: 's3', type: 'source', label: 'LlamaIndex 文档', x: 550, y: 520, vx: 0, vy: 0, weight: 3 },
        { id: 'conflict1', type: 'claim', label: '向量检索 vs 关键词检索', x: 300, y: 350, vx: 0, vy: 0, weight: 4 },
      ],
      edges: [
        { id: 'e1', source: 't1', target: 'c1', type: 'relates_to' },
        { id: 'e2', source: 't1', target: 'c2', type: 'relates_to' },
        { id: 'e3', source: 't1', target: 'c3', type: 'relates_to' },
        { id: 'e4', source: 'c1', target: 'e1', type: 'supports' },
        { id: 'e5', source: 'c2', target: 'e2', type: 'supports' },
        { id: 'e6', source: 'c3', target: 'e3', type: 'supports' },
        { id: 'e7', source: 'e1', target: 's1', type: 'derived_from' },
        { id: 'e8', source: 'e2', target: 's2', type: 'derived_from' },
        { id: 'e9', source: 'e3', target: 's3', type: 'derived_from' },
        { id: 'e10', source: 'c1', target: 'c2', type: 'relates_to' },
        { id: 'e11', source: 'conflict1', target: 'c1', type: 'contradicts' },
        { id: 'e12', source: 'conflict1', target: 'c2', type: 'contradicts' },
      ],
    };
  },

  getReports(): MockReport[] {
    return [
      {
        id: 'r1',
        title: '微服务架构拆分策略报告',
        meeting_id: 'meeting-001',
        created_at: new Date(daysAgo(2)).toISOString(),
        status: 'completed',
        summary: '基于四 Agent 讨论，输出架构决策报告，建议采用 Strangler Fig 模式分阶段迁移。',
        sections: [
          { type: 'heading', level: 1, content: '微服务架构拆分策略' },
          { type: 'paragraph', content: '本报告基于多 Agent 协同讨论结果，总结了从单体架构向微服务架构迁移的最佳实践和具体建议。' },
          { type: 'heading', level: 2, content: '核心结论' },
          { type: 'list', items: [
            '按业务域限界上下文拆分，优先拆分独立业务模块',
            '采用 strangler fig 模式渐进式迁移，避免大爆炸式重写',
            '支付模块和用户模块作为首批拆分对象',
            '建立服务间通信标准（gRPC for 同步, Kafka for 异步）'
          ]},
          { type: 'heading', level: 2, content: '风险评估' },
          { type: 'table', headers: ['风险项', '影响', '概率', '缓解措施'], rows: [
            ['分布式事务', '高', '中', 'Saga 模式 + 最终一致性'],
            ['服务间网络延迟', '中', '高', 'API Gateway 聚合 + 本地缓存'],
            ['运维复杂度上升', '高', '高', 'K8s + Service Mesh + 可观测性体系'],
          ]},
          { type: 'heading', level: 2, content: '实施计划' },
          { type: 'metric', label: '预计周期', value: '14 周', sublabel: '分 2 个阶段' },
          { type: 'metric', label: '人力投入', value: '3 人', sublabel: '全职投入' },
        ],
      },
      {
        id: 'r2',
        title: '多租户数据隔离方案决策',
        meeting_id: 'meeting-004',
        created_at: new Date(daysAgo(1)).toISOString(),
        status: 'completed',
        summary: '三种隔离方案对比与选型建议，最终选择共享数据库+行级隔离方案。',
        sections: [
          { type: 'heading', level: 1, content: '多租户数据隔离方案决策报告' },
          { type: 'paragraph', content: '经过架构师、DBA、安全专家、研发负责人四方讨论，对三种主流多租户隔离方案进行了全面评估。' },
          { type: 'metric', label: '方案评分', value: '方案三', sublabel: '共享数据库+行级隔离' },
          { type: 'heading', level: 2, content: '方案对比' },
          { type: 'table', headers: ['维度', '方案一:独立DB', '方案二:独立Schema', '方案三:行级隔离'], rows: [
            ['隔离性', '⭐⭐⭐', '⭐⭐', '⭐'],
            ['成本', '⭐', '⭐⭐', '⭐⭐⭐'],
            ['运维复杂度', '高', '中', '低'],
            ['扩展性', '高', '中', '高'],
            ['适合场景', '大型企业', '中型客户', 'SaaS 初创/中小客户'],
          ]},
          { type: 'heading', level: 2, content: '安全控制措施' },
          { type: 'list', items: [
            '中间件自动注入 tenant_id 过滤条件',
            '所有 DAO 层强制租户隔离检查',
            '审计日志记录跨租户访问尝试',
            '定期渗透测试验证隔离有效性',
          ]},
        ],
      },
      {
        id: 'r3',
        title: 'Q3 技术债偿还计划',
        meeting_id: 'meeting-003',
        created_at: new Date(daysAgo(5)).toISOString(),
        status: 'completed',
        summary: '优先级排序与资源规划，确定 3 项高优先级技术债。',
        sections: [
          { type: 'heading', level: 1, content: '2026 Q3 技术债偿还计划' },
          { type: 'heading', level: 2, content: '优先级排序' },
          { type: 'table', headers: ['技术债', '影响范围', '偿还成本', '优先级'], rows: [
            ['数据库索引优化', '全系统性能', '2 人周', 'P0'],
            ['日志体系重构', '可观测性', '3 人周', 'P0'],
            ['测试覆盖率提升', '质量保障', '4 人周', 'P0'],
            ['API 文档更新', '开发体验', '1 人周', 'P1'],
            ['依赖版本升级', '安全性', '2 人周', 'P1'],
          ]},
          { type: 'heading', level: 2, content: '资源规划' },
          { type: 'metric', label: '总投入', value: '12 人周', sublabel: 'Q3 全季度' },
          { type: 'metric', label: '预期收益', value: 'P95 -40%', sublabel: '接口延迟降低' },
        ],
      },
      {
        id: 'r4',
        title: 'K8s 集群扩缩容策略',
        meeting_id: 'meeting-007',
        created_at: new Date(daysAgo(7)).toISOString(),
        status: 'completed',
        summary: 'HPA + VPA 组合策略，引入 KEDA 支持自定义指标扩缩。',
        sections: [
          { type: 'heading', level: 1, content: 'Kubernetes 扩缩容策略' },
          { type: 'heading', level: 2, content: '策略概览' },
          { type: 'list', items: [
            'HPA：CPU > 70% 触发水平扩容，最多 10 副本',
            'VPA：内存不足时垂直扩配，不中断服务',
            'KEDA：基于 Kafka 消费队列深度自动扩缩',
            'PDB：滚动更新时最少保持 2 副本',
          ]},
          { type: 'heading', level: 2, content: '成本估算' },
          { type: 'metric', label: '月度成本', value: '¥12,000', sublabel: '5 节点集群' },
          { type: 'metric', label: '弹性节省', value: '~35%', sublabel: '对比固定配置' },
        ],
      },
    ];
  },

  getAdminStats(): Record<string, unknown> {
    return {
      users: { total: 12, active: 8, new_today: 2, by_role: { admin: 2, user: 10 } },
      meetings: { total: 47, running: 2, today: 3, this_week: 12, by_status: { done: 35, running: 4, paused: 5, pending: 3 } },
      agents: { total: 9, active: 5, by_role: { architect: 1, tech_lead: 1, ml_engineer: 1, sre: 1, pm: 1, dba: 1, security: 1, search_expert: 1, evaluator: 1 } },
      tenants: { total: 3, by_plan: { free: 1, pro: 1, enterprise: 1 } },
      system: {
        cpu_usage: 34,
        memory_usage: 62,
        db_connections: 18,
        uptime: '7天12小时',
        disk_usage: 45,
        network_io: { in: 125, out: 89 },
      },
      llm: {
        provider: 'volcengine',
        model: 'doubao-seed-2-0-code',
        temperature: 0.3,
        max_tokens: 4096,
        api_status: 'healthy',
        circuit_breaker: 'closed',
        avg_latency_ms: 2340,
        rate_limit: { rpm: 60, tpm: 100000, remaining_rpm: 42, remaining_tpm: 67800 },
      },
      plugins: {
        auth: { status: 'active', enabled: true, version: '1.2.0' },
        web_search: { status: 'active', enabled: true, version: '2.0.1' },
        memory: { status: 'active', enabled: true, version: '1.5.3' },
        code_analysis: { status: 'active', enabled: true, version: '1.1.0' },
        sandbox: { status: 'active', enabled: true, version: '1.0.2' },
        report_generator: { status: 'active', enabled: true, version: '1.3.0' },
      },
      system_health: {
        docker: { status: 'healthy', containers_running: 7, containers_total: 7 },
        sandbox_mode: 'auto',
        redis: { status: 'healthy', latency_ms: 1 },
        qdrant: { status: 'healthy', latency_ms: 5 },
        postgres: { status: 'healthy', latency_ms: 2 },
      },
      token_usage: {
        by_model: {
          'doubao-seed-2-0-code': { input_tokens: 1250000, output_tokens: 480000, total_tokens: 1730000, requests: 342 },
          'doubao-embedding': { input_tokens: 890000, output_tokens: 0, total_tokens: 890000, requests: 156 },
          'doubao-vision': { input_tokens: 45000, output_tokens: 12000, total_tokens: 57000, requests: 23 },
        },
        total_today: 2677000,
        total_this_week: 18450000,
      },
      cost: {
        daily: { today: 28.5, yesterday: 32.1, change_pct: -11.2 },
        weekly: { this_week: 189.4, last_week: 215.7, change_pct: -12.2 },
        monthly: { this_month: 742.3, last_month: 890.5, change_pct: -16.6 },
        by_service: {
          llm_api: 523.8,
          vector_db: 89.2,
          object_storage: 45.1,
          compute: 84.2,
        },
      },
      metrics_history: [
        { time: hoursAgo(24), meetings: 3, tokens: 45000, cost: 12.5 },
        { time: hoursAgo(23), meetings: 2, tokens: 32000, cost: 8.9 },
        { time: hoursAgo(22), meetings: 4, tokens: 58000, cost: 16.2 },
        { time: hoursAgo(21), meetings: 1, tokens: 18000, cost: 5.1 },
        { time: hoursAgo(20), meetings: 3, tokens: 41000, cost: 11.4 },
        { time: hoursAgo(19), meetings: 2, tokens: 29000, cost: 8.1 },
        { time: hoursAgo(18), meetings: 5, tokens: 72000, cost: 20.1 },
      ],
    };
  },

  getSystemHealth(): Record<string, unknown> {
    return {
      status: 'healthy',
      timestamp: new Date().toISOString(),
      components: {
        postgres: {
          status: 'healthy',
          latency_ms: 2,
          version: '16.1',
          connections: { active: 18, max: 100, idle: 5 },
          replication: { lag_bytes: 0, status: 'streaming' },
          db_size: '2.4 GB',
        },
        redis: {
          status: 'healthy',
          latency_ms: 1,
          version: '7.2.4',
          memory_used: '12MB',
          memory_max: '256MB',
          connected_clients: 8,
          keyspace_hits: 45230,
          keyspace_misses: 3120,
          hit_rate: 0.936,
        },
        qdrant: {
          status: 'healthy',
          latency_ms: 5,
          version: '1.11.3',
          collections: 3,
          points_count: 125000,
          disk_usage: '380MB',
        },
        docker: {
          status: 'healthy',
          version: '27.3.1',
          containers_running: 7,
          containers_total: 7,
          containers_stopped: 0,
          images_count: 12,
          network_count: 4,
          volume_count: 8,
        },
        sandbox: {
          mode: 'auto',
          image: 'python:3.12-slim',
          datascience_image: 'conclave-python-datascience:latest',
          image_available: true,
          last_pull: new Date(hoursAgo(2)).toISOString(),
          max_concurrent: 3,
          active_sandboxes: 1,
        },
        llm: {
          provider: 'volcengine',
          model: 'doubao-seed-2-0-code',
          circuit_breaker: 'closed',
          avg_latency_ms: 2340,
          p50_latency_ms: 1850,
          p95_latency_ms: 4200,
          p99_latency_ms: 6800,
          error_rate: 0.012,
          requests_last_hour: 89,
          tokens_last_hour: 245000,
        },
      },
    };
  },

  getDockerHosts(): DockerHostSummary[] {
    return [
      {
        id: 'host-local',
        name: '本地 Docker',
        host: 'unix:///var/run/docker.sock',
        status: 'connected',
        is_default: true,
        os: 'Linux 6.6.0 (WSL2)',
        arch: 'x86_64',
        cpus: 8,
        memory: '16GB',
        docker_version: '27.3.1',
        containers: { running: 7, paused: 0, stopped: 0 },
        images_count: 12,
        disk_usage: { total: '60GB', used: '28GB', available: '32GB' },
      },
      {
        id: 'host-remote-dev',
        name: '开发服务器',
        host: 'tcp://192.168.1.100:2376',
        status: 'connected',
        is_default: false,
        os: 'Ubuntu 24.04 LTS',
        arch: 'x86_64',
        cpus: 16,
        memory: '64GB',
        docker_version: '27.3.1',
        containers: { running: 12, paused: 0, stopped: 2 },
        images_count: 28,
        disk_usage: { total: '500GB', used: '180GB', available: '320GB' },
      },
      {
        id: 'host-remote-prod',
        name: '生产服务器',
        host: 'tcp://10.0.0.50:2376',
        status: 'disconnected',
        is_default: false,
        os: 'Ubuntu 22.04 LTS',
        arch: 'x86_64',
        cpus: 32,
        memory: '128GB',
        docker_version: '26.1.4',
        containers: { running: 0, paused: 0, stopped: 0 },
        images_count: 0,
        disk_usage: { total: '1TB', used: '0GB', available: '1TB' },
        last_seen: new Date(daysAgo(3)).toISOString(),
      },
    ];
  },

  getNotifications(): Record<string, unknown>[] {
    return [
      {
        id: 'notif-001',
        type: 'meeting',
        level: 'info',
        title: '会议完成',
        message: "会议 '微服务架构拆分策略讨论' 已完成",
        meeting_id: 'meeting-001',
        created_at: new Date(hoursAgo(1)).toISOString(),
        read: true,
      },
      {
        id: 'notif-002',
        type: 'system',
        level: 'success',
        title: '沙箱镜像更新',
        message: '沙箱镜像更新成功：python:3.12-slim (sha256:a3b2c4d...)',
        created_at: new Date(hoursAgo(2)).toISOString(),
        read: true,
      },
      {
        id: 'notif-003',
        type: 'llm',
        level: 'warning',
        title: 'LLM 熔断器触发',
        message: 'LLM 熔断器触发：连续 5 次请求超时，已切换至备用模型。30 秒后自动恢复。',
        created_at: new Date(hoursAgo(3)).toISOString(),
        read: true,
      },
      {
        id: 'notif-004',
        type: 'llm',
        level: 'success',
        title: 'LLM 熔断器恢复',
        message: 'LLM 熔断器已恢复：主模型 doubao-seed-2-0-code 响应正常，切换回主模型。',
        created_at: new Date(hoursAgo(2.9)).toISOString(),
        read: true,
      },
      {
        id: 'notif-005',
        type: 'meeting',
        level: 'info',
        title: '会议完成',
        message: "会议 'Q3 技术债偿还计划' 已完成，报告已生成",
        meeting_id: 'meeting-003',
        created_at: new Date(daysAgo(5)).toISOString(),
        read: true,
      },
      {
        id: 'notif-006',
        type: 'system',
        level: 'info',
        title: '数据库备份完成',
        message: '每日自动备份完成：conclave_db (2.4GB)，已同步至 OSS',
        created_at: new Date(hoursAgo(6)).toISOString(),
        read: false,
      },
      {
        id: 'notif-007',
        type: 'meeting',
        level: 'warning',
        title: '会议暂停',
        message: "会议 'AI Agent 评估体系建设' 已暂停：等待评估数据集标注完成",
        meeting_id: 'meeting-005',
        created_at: new Date(hoursAgo(3)).toISOString(),
        read: false,
      },
      {
        id: 'notif-008',
        type: 'system',
        level: 'info',
        title: '插件更新可用',
        message: 'web_search 插件有新版本 (2.1.0)，当前版本 2.0.1',
        created_at: new Date(hoursAgo(8)).toISOString(),
        read: false,
      },
      {
        id: 'notif-009',
        type: 'meeting',
        level: 'info',
        title: '新会议创建',
        message: "会议 '前端性能优化专项讨论' 已创建，等待开始",
        meeting_id: 'meeting-006',
        created_at: new Date(hoursAgo(0.5)).toISOString(),
        read: false,
      },
      {
        id: 'notif-010',
        type: 'system',
        level: 'error',
        title: '生产服务器断开',
        message: '生产服务器 (10.0.0.50) Docker 连接断开，最后在线时间：3 天前',
        created_at: new Date(daysAgo(3)).toISOString(),
        read: true,
      },
    ];
  },

  getMockUsers(): Record<string, unknown>[] {
    return [
      { id: 'user-001', username: 'admin', display_name: '演示管理员', email: 'admin@conclave.demo', role: 'admin', tenant_id: 'tenant-default', status: 'active', last_login: new Date(hoursAgo(0.5)).toISOString(), created_at: new Date(daysAgo(30)).toISOString() },
      { id: 'user-002', username: 'zhangsan', display_name: '张三', email: 'zhangsan@conclave.demo', role: 'user', tenant_id: 'tenant-default', status: 'active', last_login: new Date(hoursAgo(2)).toISOString(), created_at: new Date(daysAgo(25)).toISOString() },
      { id: 'user-003', username: 'lisi', display_name: '李四', email: 'lisi@conclave.demo', role: 'user', tenant_id: 'tenant-default', status: 'active', last_login: new Date(hoursAgo(5)).toISOString(), created_at: new Date(daysAgo(20)).toISOString() },
      { id: 'user-004', username: 'wangwu', display_name: '王五', email: 'wangwu@conclave.demo', role: 'user', tenant_id: 'tenant-research', status: 'active', last_login: new Date(daysAgo(1)).toISOString(), created_at: new Date(daysAgo(15)).toISOString() },
      { id: 'user-005', username: 'zhaoliu', display_name: '赵六', email: 'zhaoliu@conclave.demo', role: 'user', tenant_id: 'tenant-research', status: 'inactive', last_login: new Date(daysAgo(7)).toISOString(), created_at: new Date(daysAgo(15)).toISOString() },
      { id: 'user-006', username: 'sunqi', display_name: '孙七', email: 'sunqi@conclave.demo', role: 'admin', tenant_id: 'tenant-enterprise', status: 'active', last_login: new Date(hoursAgo(1)).toISOString(), created_at: new Date(daysAgo(7)).toISOString() },
    ];
  },

  getMockTenants(): Record<string, unknown>[] {
    return [
      {
        id: 'tenant-default',
        name: '默认组织',
        slug: 'default',
        plan: 'pro',
        status: 'active',
        owner_id: 'user-001',
        member_count: 8,
        meeting_count: 35,
        storage_used: '1.2GB',
        storage_limit: '10GB',
        created_at: new Date(daysAgo(30)).toISOString(),
        features: ['multi_agent', 'rag', 'sandbox', 'reports'],
      },
      {
        id: 'tenant-research',
        name: '研究团队',
        slug: 'research',
        plan: 'team',
        status: 'active',
        owner_id: 'user-004',
        member_count: 4,
        meeting_count: 12,
        storage_used: '450MB',
        storage_limit: '5GB',
        created_at: new Date(daysAgo(15)).toISOString(),
        features: ['multi_agent', 'rag', 'reports'],
      },
      {
        id: 'tenant-enterprise',
        name: '企业客户',
        slug: 'enterprise',
        plan: 'enterprise',
        status: 'active',
        owner_id: 'user-006',
        member_count: 15,
        meeting_count: 68,
        storage_used: '4.8GB',
        storage_limit: '50GB',
        created_at: new Date(daysAgo(7)).toISOString(),
        features: ['multi_agent', 'rag', 'sandbox', 'reports', 'custom_agents', 'api_access'],
      },
    ];
  },

  getMockSystemConfig(): Record<string, unknown> {
    return {
      general: {
        site_name: 'Conclave',
        site_url: 'https://conclave.demo',
        default_language: 'zh-CN',
        timezone: 'Asia/Shanghai',
        maintenance_mode: false,
      },
      llm: {
        provider: 'volcengine',
        model: 'doubao-seed-2-0-code',
        embedding_model: 'doubao-embedding',
        temperature_default: 0.3,
        max_tokens: 4096,
        timeout_seconds: 120,
        retry_count: 3,
        circuit_breaker: {
          enabled: true,
          threshold: 5,
          recovery_seconds: 30,
        },
      },
      sandbox: {
        mode: 'auto',
        image: 'python:3.12-slim',
        datascience_image: 'conclave-python-datascience:latest',
        max_concurrent: 3,
        timeout_seconds: 300,
        memory_limit: '512m',
        cpu_limit: '1.0',
        network_enabled: false,
      },
      rag: {
        chunk_size: 512,
        chunk_overlap: 50,
        top_k: 5,
        score_threshold: 0.5,
        reranker_enabled: true,
        reranker_model: 'bge-reranker-v2-m3',
      },
      security: {
        jwt_expire_minutes: 15,
        refresh_token_expire_days: 7,
        max_login_attempts: 5,
        lockout_minutes: 15,
        password_min_length: 8,
        cors_origins: ['http://localhost:5173', 'https://conclave.demo'],
      },
      storage: {
        max_upload_size_mb: 50,
        allowed_extensions: ['.md', '.markdown', '.txt'], // MR-3：与后端实际上传能力一致，禁止宣称未实现的格式
        object_storage: { provider: 'local', bucket: 'conclave-uploads' },
      },
    };
  },

  getTenants(): Record<string, unknown>[] {
    return [
      { id: 'tenant-default', name: '默认组织', slug: 'default', role: 'owner', plan: 'pro', member_count: 8, created_at: new Date(daysAgo(30)).toISOString() },
      { id: 'tenant-research', name: '研究团队', slug: 'research', role: 'admin', plan: 'team', member_count: 4, created_at: new Date(daysAgo(15)).toISOString() },
      { id: 'tenant-enterprise', name: '企业客户', slug: 'enterprise', role: 'member', plan: 'enterprise', member_count: 15, created_at: new Date(daysAgo(7)).toISOString() },
    ];
  },

  getAttachments(_meetingId: string): Record<string, unknown>[] {
    return [
      { id: 'att-1', name: '架构决策记录.md', type: 'document', size: 24576, created_at: new Date(hoursAgo(5)).toISOString() },
      { id: 'att-2', name: '性能测试报告.pdf', type: 'document', size: 1048576, created_at: new Date(hoursAgo(3)).toISOString() },
      { id: 'att-3', name: '数据流图.png', type: 'image', size: 524288, created_at: new Date(hoursAgo(2)).toISOString() },
    ];
  },

  getMetricHistory(_params?: { period?: string }): Record<string, unknown>[] {
    return [
      { time: hoursAgo(24), meetings: 3, tokens: 45000, cost: 12.5, latency_p50: 1200, latency_p95: 3400 },
      { time: hoursAgo(23), meetings: 2, tokens: 32000, cost: 8.9, latency_p50: 1100, latency_p95: 3200 },
      { time: hoursAgo(22), meetings: 4, tokens: 58000, cost: 16.2, latency_p50: 1300, latency_p95: 3800 },
      { time: hoursAgo(21), meetings: 1, tokens: 18000, cost: 5.1, latency_p50: 980, latency_p95: 2900 },
      { time: hoursAgo(20), meetings: 3, tokens: 41000, cost: 11.4, latency_p50: 1150, latency_p95: 3300 },
      { time: hoursAgo(19), meetings: 2, tokens: 29000, cost: 8.1, latency_p50: 1080, latency_p95: 3100 },
      { time: hoursAgo(18), meetings: 5, tokens: 72000, cost: 20.1, latency_p50: 1400, latency_p95: 4100 },
      { time: hoursAgo(17), meetings: 3, tokens: 48000, cost: 13.4, latency_p50: 1250, latency_p95: 3600 },
      { time: hoursAgo(16), meetings: 2, tokens: 35000, cost: 9.8, latency_p50: 1180, latency_p95: 3400 },
      { time: hoursAgo(15), meetings: 4, tokens: 55000, cost: 15.3, latency_p50: 1320, latency_p95: 3900 },
      { time: hoursAgo(14), meetings: 1, tokens: 22000, cost: 6.1, latency_p50: 1020, latency_p95: 3000 },
      { time: hoursAgo(13), meetings: 3, tokens: 43000, cost: 12.0, latency_p50: 1200, latency_p95: 3500 },
    ];
  },
};
