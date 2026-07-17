/* Conclave mock data — ported from app.html */

/* ═══ Roles ═══ */
interface Role {
  name: string;
  color: string;
}
type Roles = Record<string, Role>;

export const ROLES: Roles = {
  moderator: { name: '主持人', color: 'var(--r-moderator)' },
  architect: { name: '架构师', color: 'var(--r-architect)' },
  engineer: { name: '工程师', color: 'var(--r-engineer)' },
  security: { name: '安全专家', color: 'var(--r-security)' },
  ux: { name: 'UX设计师', color: 'var(--r-ux)' },
  data: { name: '数据工程师', color: 'var(--r-data)' },
  marketing: { name: '市场专家', color: 'var(--r-marketing)' },
};

/* ═══ Stages ═══ */
interface Stage {
  key: string;
  name: string;
  short: string;
}

export const STAGES: Stage[] = [
  { key: 'clarify', name: '澄清', short: '澄清' },
  { key: 'intra', name: '队内讨论', short: '讨论' },
  { key: 'cross', name: '跨队辩论', short: '辩论' },
  { key: 'evidence', name: '证据校验', short: '校验' },
  { key: 'arbitrate', name: '仲裁裁决', short: '仲裁' },
  { key: 'produce', name: '产出交付', short: '产出' },
];

/* ═══ Meeting messages ═══ */
export interface MeetingMessage {
  stage: number;
  role: string;
  time: string;
  content: string;
  refs?: string[];
  risk?: string | null;
}

export const MESSAGES: MeetingMessage[] = [
  // Stage 1: 澄清
  {
    stage: 0,
    role: 'moderator',
    time: '14:00:05',
    content:
      '<p>各位专家好。本次议题：<strong>将现有单体电商平台迁移至微服务架构</strong>。产出类型为PRD文档。</p><p>请围绕迁移路径、服务拆分粒度、基础设施要求三方面展开讨论。架构师先给出对现状的判断，各角色依次补充视角。</p>',
    refs: [],
    risk: null,
  },
  // Stage 2: 队内讨论
  {
    stage: 1,
    role: 'architect',
    time: '14:08:12',
    content:
      '<p>基于代码库分析，当前单体约28万行Java代码，核心模块包括商品、订单、支付、库存、用户、推荐六部分。</p><p>建议按领域驱动设计拆分，优先拆出边界清晰的服务：用户服务（认证、Profile、权限，无状态，独立部署风险低）、商品服务（读多写少，可独立缓存）。订单、支付、库存三者存在强一致性约束，初期保持聚合，避免分布式事务。</p>',
    refs: ['规格 §3.2', 'martinfowler.com'],
    risk: null,
  },
  {
    stage: 1,
    role: 'engineer',
    time: '14:15:30',
    content:
      '<p>从工程实践补充几点关键决策：</p><p>服务间通信推荐 gRPC 做内部同步调用，事件总线做异步解耦。订单到库存的扣减场景建议用 Saga 模式而非 2PC，避免长事务锁。</p><p>可观测性方面，拆分前必须先建立分布式追踪（OpenTelemetry）、统一日志、指标监控。没有观测能力的微服务等于生产事故。</p><p>CI/CD 需要从单条 pipeline 升级为多服务独立 pipeline，基础设施成本预估增加约 40%。</p>',
    refs: ['arxiv:1706.04024'],
    risk: 'high',
  },
  {
    stage: 1,
    role: 'security',
    time: '14:22:08',
    content:
      '<p>从安全维度必须指出四个问题：</p><p>服务间认证——当前单体内部调用无鉴权，拆分后每个服务边界都需要 mTLS 或 JWT。API 网关须在流量入口统一处理认证、限流、WAF。数据隔离须保证敏感数据（支付、手机号）的访问控制，每服务独立 DB 账号、最小权限。</p><p>Saga 补偿事务的失败场景需要告警和人工介入通道，不能假设补偿一定成功。</p>',
    refs: ['owasp.org/ms-top10'],
    risk: 'high',
  },
  {
    stage: 1,
    role: 'ux',
    time: '14:28:45',
    content:
      '<p>从用户视角提醒：迁移过程中前端无感是核心目标。BFF（Backend For Frontend）层是必要的，否则前端要对接 N 个服务，版本协调会成为持续噩梦。</p><p>建议 BFF 按客户端类型拆分（Web / Mobile），对前端保持统一 API 契约。灰度发布期间要保证购物车、订单状态不出现数据丢失或重复。</p>',
    refs: [],
    risk: 'mid',
  },
  {
    stage: 1,
    role: 'data',
    time: '14:35:20',
    content:
      '<p>对架构师的拆分方案提出数据层异议。</p><p>订单、库存、支付虽然强一致，但这三者的数据被数据分析和推荐系统大量跨域 join。如果保持聚合，后续 BI 报表和实时推荐特征工程都会遇到跨库查询问题。</p><p>建议：聚合服务可先不拆，但必须提前规划 CDC 管道，通过 Debezium 把变更实时同步到数据湖。否则数据团队在迁移完成后会"失明"三到六个月。</p>',
    refs: ['debezium.io'],
    risk: 'mid',
  },
  {
    stage: 1,
    role: 'marketing',
    time: '14:42:10',
    content:
      '<p>从业务侧补充约束。Q4 是电商旺季（双十一、黑五），任何架构迁移必须在九月底前完成核心链路，否则建议推迟到明年 Q1。</p><p>迁移期间营销系统（优惠券、秒杀、拼团）的功能迭代不能停。这意味着新服务必须支持并行开发——老团队维护单体，新团队在微服务上做新功能。这是架构拆分必须考虑的组织约束。</p><p>建议 PRD 中明确功能冻结窗口和回滚预案，业务团队至少需要两周稳定观察期。</p>',
    refs: [],
    risk: null,
  },
  // Stage 3: 跨队辩论
  {
    stage: 2,
    role: 'architect',
    time: '14:50:00',
    content:
      '<p>回应各位意见并修正方案：</p><p>对数据工程师的 CDC 建议——完全同意。修正方案为在拆分任何服务前，先部署 CDC 管道作为数据层基础，纳入 Phase 0。</p><p>对市场专家的 Q4 约束——6 到 9 个月预估已覆盖到 Q4，调整为分三期：Phase 1（5-7月）基础设施加用户商品服务拆分；Phase 2（8-9月）订单聚合加支付库存；Phase 3（Q1 次年）推荐营销等边缘服务。Q4 前核心链路完成迁移并留一个月观察期。</p><p>对安全专家——mTLS 和服务网格纳入 Phase 0 基础设施。</p>',
    refs: [],
    risk: null,
  },
  {
    stage: 2,
    role: 'data',
    time: '14:55:30',
    content:
      '<p>补充确认：CDC 管道建议使用 Debezium + Kafka Connect，先同步到数据湖（Iceberg 表格式），BI 和推荐系统从数据湖读取，不直接查询业务库。这样迁移过程中数据消费方无感知。</p><p>一个风险点：Debezium 对 DDL 变更的兼容性有限，迁移期间需要冻结数据库 schema 变更，或提前测试 DDL 兼容矩阵。</p>',
    refs: ['debezium.io'],
    risk: 'low',
  },
  // Stage 4: 证据校验 (current)
  {
    stage: 3,
    role: 'moderator',
    time: '15:02:00',
    content:
      '<p>进入证据校验阶段。正在对架构师引用的 Saga 模式论文进行交叉验证，同时对安全专家引用的 OWASP 微服务安全清单进行来源核验。</p><p>请各位保持待命，如有补充证据请及时提交。</p>',
    refs: [],
    risk: null,
  },
  {
    stage: 3,
    role: 'moderator',
    time: '15:05:15',
    content:
      '<p>Saga 论文核验完成。该论文为 Garcia-Molina 1987 年经典 Saga 论文，被微服务社区广泛采纳。</p><p>补充：现代实践中 Saga 分为编排式（Orchestration）和协调式（Choreography）。我们的场景适合编排式，由订单服务作为协调者，补偿事务由各服务自行实现。该模式已在 microservices.io 有完整的模式描述和反模式案例。</p>',
    refs: ['arxiv:1706.04024', 'microservices.io', 'Garcia-Molina 1987'],
    risk: null,
  },
  {
    stage: 3,
    role: 'moderator',
    time: '15:08:00',
    content:
      '<p>OWASP 微服务安全清单核验完成。来源可信，MS-Top10 中的服务间认证、API 网关、数据隔离三项与本会议讨论高度相关。安全专家的建议有据可查。</p><p>一项修正：OWASP 建议的 mTLS 是服务网格的标配，但 Istio 引入的运维复杂度需要评估。建议 Phase 0 先用 Linkerd 轻量方案，Phase 2 再评估是否迁移到 Istio。</p>',
    refs: ['owasp.org/ms-top10', 'linkerd.io'],
    risk: null,
  },
];

/* ═══ Meetings ═══ */
interface Meeting {
  id: string;
  title: string;
  status: string;
  progress: string;
  date: string;
  topic: string;
}

export const MEETINGS: Meeting[] = [
  { id: 'demo-001', title: '微服务架构迁移方案', status: 'running', progress: '3/6', date: '07-16 14:00', topic: '将现有单体电商平台迁移至微服务架构' },
  { id: 'demo-002', title: 'Q3产品路线图评审', status: 'done', progress: '6/6', date: '07-14 09:00', topic: '确定Q3季度产品方向和优先级' },
  { id: 'demo-003', title: '用户增长策略讨论', status: 'paused', progress: '2/6', date: '07-12 15:30', topic: '新用户获取和留存策略' },
  { id: 'demo-004', title: '数据中台技术选型', status: 'done', progress: '6/6', date: '07-10 10:00', topic: '数据中台技术栈选型与架构设计' },
  { id: 'demo-005', title: '移动端性能优化方案', status: 'done', progress: '6/6', date: '07-08 14:00', topic: 'App启动速度和首屏渲染优化' },
  { id: 'demo-006', title: '国际化多语言架构', status: 'error', progress: '4/6', date: '07-06 11:00', topic: '多语言支持和国际化架构设计' },
  { id: 'demo-007', title: '支付系统容灾方案', status: 'done', progress: '6/6', date: '07-04 16:00', topic: '支付链路高可用和容灾切换' },
  { id: 'demo-008', title: '推荐算法重构评审', status: 'done', progress: '6/6', date: '07-02 09:30', topic: '推荐系统算法升级和工程重构' },
  { id: 'demo-009', title: 'API网关选型分析', status: 'done', progress: '6/6', date: '06-30 14:00', topic: 'Kong vs APISIX vs自研网关选型' },
  { id: 'demo-010', title: '微服务监控体系设计', status: 'done', progress: '6/6', date: '06-28 10:30', topic: '分布式追踪和监控告警体系' },
  { id: 'demo-011', title: '容器化迁移评估', status: 'done', progress: '6/6', date: '06-26 15:00', topic: '从虚拟机到K8s容器化迁移' },
  { id: 'demo-012', title: '安全合规审计准备', status: 'done', progress: '6/6', date: '06-24 09:00', topic: '等保三级合规审计准备' },
];

/* ═══ Models ═══ */
interface Model {
  name: string;
  desc: string;
  status: string;
  tag: string;
}

export const MODELS: Model[] = [
  { name: 'Qwen2.5-72B-Instruct', desc: '通义千问主力模型，通用能力强', status: 'active', tag: '主力' },
  { name: 'DeepSeek-V3', desc: '深度求索推理模型，擅长代码和逻辑', status: 'active', tag: '推理' },
  { name: 'bge-m3', desc: '多语言嵌入模型，用于RAG检索', status: 'active', tag: '嵌入' },
  { name: 'bge-reranker-v2-m3', desc: '重排序模型，用于检索结果精排', status: 'standby', tag: '重排' },
];

/* ═══ Model center data (from real backend llm_providers.py) ═══ */
interface Provider {
  id: string;
  name: string;
  baseUrl: string;
  hasKey: boolean;
  balance: string;
  currency: string;
  models: number;
  supportsBalance: boolean;
  pricingNote: string;
}

export const PROVIDERS: Provider[] = [
  { id: 'siliconflow', name: '硅基流动', baseUrl: 'api.siliconflow.cn', hasKey: true, balance: '¥42.18', currency: 'CNY', models: 38, supportsBalance: true, pricingNote: '按百万Token计费，部分小模型免费' },
  { id: 'deepseek', name: 'DeepSeek', baseUrl: 'api.deepseek.com', hasKey: true, balance: '¥128.50', currency: 'CNY', models: 6, supportsBalance: true, pricingNote: 'DeepSeek-V3 输入¥2/百万，输出¥8/百万' },
  { id: 'openai', name: 'OpenAI', baseUrl: 'api.openai.com', hasKey: false, balance: '—', currency: 'USD', models: 12, supportsBalance: false, pricingNote: 'GPT-4o 输入$2.5/百万，输出$10/百万' },
  { id: 'openrouter', name: 'OpenRouter', baseUrl: 'openrouter.ai', hasKey: false, balance: '—', currency: 'USD', models: 200, supportsBalance: true, pricingNote: '返回模型列表含定价信息' },
  { id: 'custom', name: '自定义', baseUrl: '—', hasKey: false, balance: '—', currency: '', models: 0, supportsBalance: false, pricingNote: '任意 OpenAI 兼容接口' },
];

interface ModelCatalogItem {
  id: string;
  name: string;
  provider: string;
  input: number;
  output: number;
  tier: string;
  score: number | null;
  cat: string;
  desc: string;
  recommended?: boolean;
}

export const MODEL_CATALOG: ModelCatalogItem[] = [
  { id: 'deepseek-ai/DeepSeek-V4-Pro', name: 'DeepSeek-V4-Pro', provider: 'siliconflow', input: 12.0, output: 24.0, tier: 'pro', score: 95, cat: 'chat', desc: '推理能力最强，适合仲裁阶段' },
  { id: 'deepseek-ai/DeepSeek-V4-Flash', name: 'DeepSeek-V4-Flash', provider: 'siliconflow', input: 1.0, output: 2.0, tier: 'fast', score: 85, cat: 'chat', desc: '快速响应，成本低，延迟73s' },
  { id: 'deepseek-ai/DeepSeek-V3.2', name: 'DeepSeek-V3.2', provider: 'siliconflow', input: 4.0, output: 6.0, tier: 'standard', score: 88, cat: 'chat', recommended: true, desc: '强JSON遵循，性价比高' },
  { id: 'deepseek-ai/DeepSeek-R1', name: 'DeepSeek-R1', provider: 'siliconflow', input: 4.0, output: 16.0, tier: 'reasoning', score: 92, cat: 'reasoning', recommended: true, desc: '推理模型，深度思考，适合复杂推理' },
  { id: 'deepseek-ai/DeepSeek-R1-0528-Qwen3-8B', name: 'DeepSeek-R1-8B', provider: 'siliconflow', input: 0.0, output: 0.0, tier: 'free', score: 78, cat: 'free', recommended: true, desc: '推理模型，免费使用' },
  { id: 'zai-org/GLM-5.2', name: 'GLM-5.2', provider: 'siliconflow', input: 8.0, output: 28.0, tier: 'standard', score: 99, cat: 'chat', recommended: true, desc: '基准测试均分98.8，适合 clarify/arbitrate/produce' },
  { id: 'zai-org/GLM-5.1', name: 'GLM-5.1', provider: 'siliconflow', input: 4.0, output: 16.0, tier: 'standard', score: 90, cat: 'chat', desc: '通用能力强，价格适中' },
  { id: 'MiniMaxAI/MiniMax-M2.5', name: 'MiniMax-M2.5', provider: 'siliconflow', input: 2.1, output: 8.4, tier: 'standard', score: 90, cat: 'chat', recommended: true, desc: '性价比之王，推理满分，14.2s' },
  { id: 'ByteDance-Seed/Seed-OSS-36B-Instruct', name: 'Seed-OSS-36B', provider: 'siliconflow', input: 1.5, output: 4.0, tier: 'standard', score: 81, cat: 'chat', recommended: true, desc: '响应最快6s，成本最低' },
  { id: 'THUDM/GLM-Z1-9B-0414', name: 'GLM-Z1-9B', provider: 'siliconflow', input: 0.0, output: 0.0, tier: 'free', score: 75, cat: 'free', recommended: true, desc: '9B推理模型，免费使用' },
  { id: 'moonshotai/Kimi-K2.6', name: 'Kimi-K2.6', provider: 'siliconflow', input: 4.0, output: 16.0, tier: 'standard', score: 87, cat: 'chat', desc: '月之暗面通用模型' },
  { id: 'moonshotai/Kimi-K2.7-Code', name: 'Kimi-K2.7-Code', provider: 'siliconflow', input: 6.5, output: 27.0, tier: 'standard', score: 86, cat: 'chat', desc: '代码能力突出' },
  { id: 'tencent/Hunyuan-A13B-Instruct', name: 'Hunyuan-A13B', provider: 'siliconflow', input: 1.0, output: 4.0, tier: 'standard', score: 79, cat: 'chat', desc: '腾讯混元，MoE架构' },
  { id: 'stepfun-ai/Step-3.5-Flash', name: 'Step-3.5-Flash', provider: 'siliconflow', input: 0.7, output: 2.1, tier: 'fast', score: 76, cat: 'chat', desc: '阶跃星辰快速模型' },
  { id: 'inclusionAI/Ling-flash-2.0', name: 'Ling-flash-2.0', provider: 'siliconflow', input: 1.0, output: 4.0, tier: 'standard', score: 70, cat: 'chat', desc: '蚂蚁Ling系列' },
  { id: 'inclusionAI/Ling-mini-2.0', name: 'Ling-mini-2.0', provider: 'siliconflow', input: 0.5, output: 2.0, tier: 'cheap', score: 77, cat: 'free', desc: '经济型，3.7s延迟' },
  { id: 'BAAI/bge-m3', name: 'bge-m3', provider: 'siliconflow', input: 0.0, output: 0.0, tier: 'free', score: null, cat: 'embedding', desc: '多语言嵌入模型，RAG检索' },
  { id: 'BAAI/bge-reranker-v2-m3', name: 'bge-reranker-v2-m3', provider: 'siliconflow', input: 0.0, output: 0.0, tier: 'free', score: null, cat: 'embedding', desc: '重排序模型，检索精排' },
];

interface StageModel {
  stage: string;
  stageEn: string;
  model: string;
  score: string;
  cost: string;
  reason: string;
}

export const STAGE_MODELS: StageModel[] = [
  { stage: '澄清', stageEn: 'clarify', model: 'zai-org/GLM-5.2', score: '98.8', cost: '¥8.0', reason: '需求澄清必须准确，错误代价大' },
  { stage: '队内讨论', stageEn: 'intra_team', model: 'ByteDance-Seed/Seed-OSS-36B-Instruct', score: '80.8', cost: '¥1.5', reason: '发散讨论需要速度，6s完胜' },
  { stage: '跨队辩论', stageEn: 'cross_team', model: 'MiniMaxAI/MiniMax-M2.5', score: '90.4', cost: '¥2.1', reason: '交叉论证需要推理满分' },
  { stage: '证据校验', stageEn: 'evidence_check', model: 'MiniMaxAI/MiniMax-M2.5', score: '90.4', cost: '¥2.1', reason: '证据对照需要抗幻觉95分' },
  { stage: '仲裁裁决', stageEn: 'arbitrate', model: 'zai-org/GLM-5.2', score: '98.8', cost: '¥8.0', reason: '最终裁决不可妥协，必须最高质量' },
  { stage: '产出交付', stageEn: 'produce', model: 'zai-org/GLM-5.2', score: '98.8', cost: '¥8.0', reason: '产出报告面向用户，质量优先' },
];

/* ═══ Monitor data ═══ */
interface HealthCheck {
  name: string;
  desc: string;
  status: string;
  latency: string;
  detail: string;
}

export const HEALTH_CHECKS: HealthCheck[] = [
  { name: 'PostgreSQL', desc: '主数据库 + pgvector 向量存储', status: 'ok', latency: '3ms', detail: '16个连接活跃' },
  { name: 'Redis', desc: '会话缓存 / 限流 / 任务队列', status: 'ok', latency: '1ms', detail: '内存占用 128MB / 512MB' },
  { name: 'Qdrant', desc: '向量数据库（RAG文档检索）', status: 'ok', latency: '5ms', detail: '3个collection · 12,847条向量' },
  { name: 'Docker Engine', desc: '沙箱容器运行时（通过 Socket Proxy）', status: 'ok', latency: '12ms', detail: '4个容器运行中' },
  { name: 'LLM 熔断器', desc: 'SiliconFlow API 连接保护', status: 'closed', latency: '—', detail: '正常状态，无熔断' },
  { name: 'Web搜索服务', desc: 'Playwright + noVNC 远程浏览器', status: 'ok', latency: '—', detail: '空闲，最近请求 14:22' },
];

interface Metric {
  label: string;
  value: string;
  unit: string;
  trend: string;
  bar: number;
}

export const METRICS: Metric[] = [
  { label: '会议总数', value: '147', unit: '', trend: '↗ +12 本周', bar: 0.6 },
  { label: '运行中会议', value: '1', unit: '', trend: '微服务架构迁移', bar: 0.05 },
  { label: '今日Token消耗', value: '48.2', unit: 'k', trend: '↘ 较昨日 -18%', bar: 0.3 },
  { label: '今日成本', value: '0.34', unit: '¥', trend: '¥9.70 本周累计', bar: 0.15 },
  { label: '平均响应延迟', value: '14.2', unit: 's', trend: 'MiniMax-M2.5 基准', bar: 0.4 },
  { label: 'API成功率', value: '99.6', unit: '%', trend: '最近24h', bar: 0.996 },
];

interface CircuitBreaker {
  label: string;
  value: string;
  indicator: string;
}

export const CIRCUIT_BREAKER: CircuitBreaker[] = [
  { label: '当前状态', value: 'closed', indicator: 'closed' },
  { label: '失败次数', value: '0', indicator: '' },
  { label: '成功次数', value: '1,247', indicator: '' },
  { label: '熔断阈值', value: '5次/60s', indicator: '' },
  { label: '半开恢复', value: '30s后', indicator: '' },
  { label: '回退Provider', value: 'DeepSeek → OpenAI', indicator: '' },
];

interface SystemEvent {
  time: string;
  level: string;
  msg: string;
}

export const EVENTS: SystemEvent[] = [
  { time: '15:08', level: 'INFO', msg: 'OWASP安全清单核验完成，证据校验通过' },
  { time: '14:58', level: 'INFO', msg: '跨队辩论阶段完成，识别共识3项' },
  { time: '14:45', level: 'WARN', msg: '市场专家提出Q4旺季约束，需调整时间线' },
  { time: '14:22', level: 'WARN', msg: '安全专家标记2项高风险问题' },
  { time: '14:15', level: 'WARN', msg: '工程师标记可观测性为高风险' },
  { time: '14:00', level: 'INFO', msg: '主持人启动会议，议题已分发' },
  { time: '13:55', level: 'INFO', msg: 'Redis 缓存命中率 94.2%' },
  { time: '13:48', level: 'INFO', msg: 'Qdrant 向量索引完成 12,847条' },
  { time: '13:30', level: 'INFO', msg: 'Docker 沙箱预热完成' },
  { time: '13:20', level: 'INFO', msg: 'SiliconFlow 定价表已更新（25个模型）' },
];

/* ═══ Topology data ═══ */
interface TopologyNode {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  sub: string;
}

export const TOPOLOGY_NODES: TopologyNode[] = [
  { id: 'frontend', x: 300, y: 40, w: 120, h: 40, label: 'Frontend', sub: 'nginx :5173' },
  { id: 'backend', x: 300, y: 130, w: 120, h: 40, label: 'Backend', sub: 'FastAPI :8000' },
  { id: 'postgres', x: 60, y: 220, w: 120, h: 40, label: 'PostgreSQL', sub: ':5432' },
  { id: 'redis', x: 220, y: 220, w: 120, h: 40, label: 'Redis', sub: ':6379' },
  { id: 'qdrant', x: 380, y: 220, w: 120, h: 40, label: 'Qdrant', sub: ':6333' },
  { id: 'socket-proxy', x: 540, y: 130, w: 120, h: 40, label: 'Docker Proxy', sub: ':2375' },
  { id: 'sandbox-l1', x: 540, y: 220, w: 120, h: 40, label: 'Sandbox L1', sub: '--network none' },
  { id: 'sandbox-l2', x: 540, y: 300, w: 120, h: 40, label: 'Sandbox L2', sub: 'DNS过滤' },
  { id: 'dns', x: 380, y: 300, w: 120, h: 40, label: 'DNS Proxy', sub: 'dnsmasq' },
  { id: 'llm', x: 300, y: 370, w: 120, h: 40, label: 'SiliconFlow', sub: 'api.siliconflow.cn' },
];

interface TopologyLink {
  from: string;
  to: string;
  type: string;
}

export const TOPOLOGY_LINKS: TopologyLink[] = [
  { from: 'frontend', to: 'backend', type: 'active' },
  { from: 'backend', to: 'postgres', type: 'active' },
  { from: 'backend', to: 'redis', type: 'active' },
  { from: 'backend', to: 'qdrant', type: 'active' },
  { from: 'backend', to: 'socket-proxy', type: 'active' },
  { from: 'socket-proxy', to: 'sandbox-l1', type: 'dashed' },
  { from: 'socket-proxy', to: 'sandbox-l2', type: 'dashed' },
  { from: 'sandbox-l2', to: 'dns', type: 'active' },
  { from: 'backend', to: 'llm', type: 'active' },
];

interface NetworkLayer {
  name: string;
  desc: string;
  tag: string;
}

export const NETWORK_LAYERS: NetworkLayer[] = [
  { name: 'L1 无网络', desc: '完全隔离的代码执行沙箱，无任何网络访问', tag: '--network none' },
  { name: 'L2 DNS过滤', desc: '通过自定义网络 + dnsmasq 代理，仅解析白名单域名（pypi等）', tag: 'conclave-sandbox-l2' },
  { name: 'L3 全联网', desc: '标准 bridge 网络，需用户显式授权，用于Web搜索任务', tag: '--network bridge' },
  { name: '内部网络', desc: '后端与所有基础服务间的通信网络，不暴露给沙箱', tag: 'conclave-internal' },
];

interface Connection {
  from: string;
  to: string;
  port: string;
  status: string;
}

export const CONNECTIONS: Connection[] = [
  { from: 'Frontend', to: 'Backend', port: 'HTTP :5173→:8000', status: 'ok' },
  { from: 'Backend', to: 'PostgreSQL', port: 'TCP :5432', status: 'ok' },
  { from: 'Backend', to: 'Redis', port: 'TCP :6379', status: 'ok' },
  { from: 'Backend', to: 'Qdrant', port: 'HTTP :6333', status: 'ok' },
  { from: 'Backend', to: 'Docker Proxy', port: 'TCP :2375', status: 'ok' },
  { from: 'Backend', to: 'SiliconFlow', port: 'HTTPS :443', status: 'ok' },
  { from: 'Docker Proxy', to: 'Sandbox L1', port: 'containerd', status: 'ok' },
  { from: 'Sandbox L2', to: 'DNS Proxy', port: 'UDP :53', status: 'ok' },
];

/* ═══ Command palette (cmd+k) ═══ */
export type CmdkAction =
  | 'landing'
  | 'board'
  | 'meeting'
  | 'report'
  | 'models'
  | 'monitor'
  | 'topology'
  | 'settings'
  | 'toggleTheme'
  | 'toggleLog';

interface CmdkItem {
  icon: string;
  label: string;
  action: CmdkAction;
  shortcut?: string;
}

export const CMDK_ITEMS: CmdkItem[] = [
  { icon: 'M3 10.5L12 3l9 7.5M5 9.5V21h14V9.5M9.5 21v6h5v6', label: '返回首页', action: 'landing', shortcut: '' },
  { icon: 'M5 7h14M5 12h14M5 17h14', label: '查看会议看板', action: 'board', shortcut: '' },
  { icon: 'M4 5h16v12H8l-4 4z', label: '进入当前会议', action: 'meeting', shortcut: '' },
  { icon: 'M7 7h10v10H7z', label: '模型中心', action: 'models', shortcut: '' },
  { icon: 'M3 12h4l2-6 4 12 2-6h6', label: '监控面板', action: 'monitor', shortcut: '' },
  { icon: 'M5 6a2 2 0 1 0 4 0 2 2 0 1 0-4 0M15 6a2 2 0 1 0 4 0 2 2 0 1 0-4 0M10 18a2 2 0 1 0 4 0 2 2 0 1 0-4 0M7 6h10M6.5 7.5L10.5 16M17.5 7.5L13.5 16', label: '组件联通', action: 'topology', shortcut: '' },
  { icon: 'M12 3v2M12 19v2M3 12h2M19 12h2', label: '切换深色模式', action: 'toggleTheme', shortcut: '⌘D' },
  { icon: 'M5 5h14v14H5z', label: '打开日志面板', action: 'toggleLog', shortcut: '⌘L' },
  { icon: 'M4 12l16-8-6 16-3-7z', label: '新建会议', action: 'landing', shortcut: '⌘N' },
];

/* ═══ Logs ═══ */
interface LogEntry {
  time: string;
  level: string;
  msg: string;
}

export const LOGS: LogEntry[] = [
  { time: '15:08:00', level: 'INFO', msg: 'OWASP安全清单核验完成，来源可信' },
  { time: '15:07:45', level: 'INFO', msg: 'microservices.io 模式描述页面抓取成功' },
  { time: '15:06:30', level: 'DEBUG', msg: '正在解析 Garcia-Molina 1987 Saga 论文引用' },
  { time: '15:05:15', level: 'INFO', msg: 'Saga论文交叉验证完成，确认来源可靠' },
  { time: '15:04:00', level: 'DEBUG', msg: 'Web搜索: "Saga pattern microservices orchestration"' },
  { time: '15:03:20', level: 'DEBUG', msg: 'RAG检索: query="Saga模式 补偿事务" chunks=3' },
  { time: '15:02:00', level: 'INFO', msg: '进入证据校验阶段' },
  { time: '15:01:50', level: 'INFO', msg: '跨队辩论阶段完成，识别共识3项' },
  { time: '14:58:10', level: 'DEBUG', msg: '仲裁准备: 提取争议点2项' },
  { time: '14:55:30', level: 'INFO', msg: '数据工程师补充CDC管道方案' },
  { time: '14:50:00', level: 'INFO', msg: '架构师修正拆分方案为三期迁移' },
  { time: '14:48:00', level: 'DEBUG', msg: '跨队辩论: 检测到1项数据层异议' },
  { time: '14:45:20', level: 'WARN', msg: '市场专家提出Q4旺季约束，需调整时间线' },
  { time: '14:42:10', level: 'INFO', msg: '市场专家发言完成' },
  { time: '14:35:20', level: 'INFO', msg: '数据工程师提出数据层异议' },
  { time: '14:28:45', level: 'INFO', msg: 'UX设计师建议BFF层方案' },
  { time: '14:22:08', level: 'WARN', msg: '安全专家标记2项高风险问题' },
  { time: '14:15:30', level: 'WARN', msg: '工程师标记可观测性为高风险' },
  { time: '14:08:12', level: 'INFO', msg: '架构师发表拆分方案' },
  { time: '14:00:05', level: 'INFO', msg: '主持人启动会议，议题已分发' },
];
