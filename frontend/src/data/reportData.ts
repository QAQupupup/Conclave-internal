/* Conclave report data — ported from app.html */

/* ═══ Shared interfaces ═══ */

export interface ReportType {
  id: string;
  label: string;
}

export interface TeamMember {
  role: string;
  stance: string;
}

export interface Conflict {
  id: string;
  type: string;
  summary: string;
  sideA: string;
  sideB: string;
  verdict: string;
  rationale: string;
  trace: string;
}

export interface Decision {
  conflictId: string;
  verdict: string;
  rationale: string;
}

export interface Attachment {
  filename: string;
  size: number;
  ext: string;
}

export interface PrdArtifact {
  title: string;
  goal: string;
  scope: string;
  assumptions: string[];
  constraints: string[];
  apiEndpoints: string[];
  openQuestions: string[];
}

export interface LlmTrace {
  totalCalls: number;
  successRate: string;
  totalTokens: string;
  inputTokens: string;
  outputTokens: string;
}

/* ═══ PRD report data (REPORT_DATA) ═══ */

export interface PrdReportData {
  meetingId: string;
  topic: string;
  deliverableType: string;
  status: string;
  clarifiedTopic: string;
  keyQuestions: string[];
  teamConfig: TeamMember[];
  conflicts: Conflict[];
  decisions: Decision[];
  adoptedClaims: string[];
  confidence: Record<string, string>;
  llmTrace: LlmTrace;
  artifact: {
    prd: PrdArtifact;
    openapi: string;
    attachments: Attachment[];
  };
}

export const REPORT_DATA: PrdReportData = {
  meetingId:'mtg-3df652f78aa9',
  topic:'将现有单体电商平台迁移至微服务架构',
  deliverableType:'prd_openapi',
  status:'done',
  clarifiedTopic:'围绕迁移路径、服务拆分粒度、基础设施要求三方面，评估单体电商平台的微服务化改造方案，产出可执行的PRD文档。',
  keyQuestions:[
    '服务拆分粒度如何确定？哪些模块优先拆分？',
    '订单-库存-支付的强一致性如何在分布式环境下保证？',
    '迁移期间如何保证业务连续性，特别是Q4旺季约束？',
    '数据团队在迁移过程中的跨库查询问题如何解决？',
    '安全边界从单体内部调用到服务间认证的过渡方案？'
  ],
  teamConfig:[
    {role:'主持人',stance:'议题引导与阶段管理'},
    {role:'架构师',stance:'主张DDD拆分，三期迁移'},
    {role:'工程师',stance:'主张Saga模式，强调可观测性'},
    {role:'安全专家',stance:'主张mTLS与API网关前置'},
    {role:'UX设计师',stance:'主张BFF层保证前端无感'},
    {role:'数据工程师',stance:'主张CDC管道优先部署'},
    {role:'市场专家',stance:'主张Q4前完成核心链路'}
  ],
  conflicts:[
    {id:'C1',type:'preference',summary:'订单聚合服务是否立即拆分',sideA:'架构师：初期保持聚合，避免分布式事务',sideB:'数据工程师：不拆会导致跨库查询失明',verdict:'compromise',rationale:'维持聚合但提前部署CDC管道，数据通过数据湖消费，不直接查询业务库',trace:'cross_team · msg-8'},
    {id:'C2',type:'factual',summary:'Saga模式 vs 2PC用于订单-库存扣减',sideA:'工程师：推荐Saga编排式',sideB:'（无直接反对方，安全专家补充风险提示）',verdict:'a',rationale:'Garcia-Molina 1987论文验证，编排式适合订单服务作为协调者的场景',trace:'evidence_check · msg-10'},
    {id:'C3',type:'scope',summary:'服务网格选型 Istio vs Linkerd',sideA:'安全专家：推荐Istio功能全面',sideB:'架构师：Istio运维复杂度过高',verdict:'compromise',rationale:'Phase 0先用Linkerd轻量方案，Phase 2再评估是否迁移到Istio',trace:'evidence_check · msg-11'}
  ],
  decisions:[
    {conflictId:'C1',verdict:'compromise',rationale:'维持聚合，但Phase 0优先部署CDC'},
    {conflictId:'C2',verdict:'a',rationale:'采用Saga编排式'},
    {conflictId:'C3',verdict:'compromise',rationale:'先用Linkerd，后期评估Istio'}
  ],
  adoptedClaims:[
    '绞杀者模式（Strangler Fig）作为迁移路径',
    'gRPC用于内部同步调用，Kafka用于异步解耦',
    'OpenTelemetry + ELK + Prometheus建立可观测性',
    'Phase 0部署CDC管道（Debezium + Kafka Connect + Iceberg）',
    '分三期迁移：Phase 1(5-7月)基础+用户商品，Phase 2(8-9月)订单聚合+支付库存，Phase 3(Q1次年)推荐营销',
    'mTLS + 服务网格纳入Phase 0基础设施',
    'Q4前核心链路完成迁移并留1个月观察期'
  ],
  confidence:{clarify:'high',intra_team:'high',cross_team:'high',evidence_check:'high',arbitrate:'high',produce:'high'},
  llmTrace:{totalCalls:28,successRate:'100%',totalTokens:'48,213',inputTokens:'31,045',outputTokens:'17,168'},
  artifact:{
    prd:{
      title:'电商平台微服务架构迁移 PRD',
      goal:'将现有28万行单体Java电商系统分三期迁移至微服务架构，保证Q4旺季前核心链路完成迁移，迁移过程前端无感，数据团队无失明期。',
      scope:'覆盖商品、订单、支付、库存、用户、推荐六大核心模块的拆分，基础设施搭建（CDC、可观测性、服务网格），CI/CD升级。不含前端框架重构和数据库品牌更换。',
      assumptions:['现有单体代码可逐步抽离接口边界','团队可并行维护单体和新微服务','迁移期间DB schema变更可冻结'],
      constraints:['Q4旺季（双十一/黑五）前完成核心链路','迁移期间营销系统功能迭代不能停','基础设施成本增加不超过40%'],
      apiEndpoints:['POST /api/v2/users/register','GET /api/v2/products/{id}','POST /api/v2/orders','POST /api/v2/orders/{id}/pay','PUT /api/v2/inventory/deduct','GET /api/v2/recommendations/{userId}'],
      openQuestions:['CDC对DDL变更的兼容性矩阵需测试','Linkerd到Istio迁移的具体触发条件','BFF层是否需要独立部署团队']
    },
    openapi:'openapi: 3.0.0\ninfo:\n  title: E-Commerce Microservices API\n  version: "2.0"\n  description: 微服务拆分后的接口契约\npaths:\n  /api/v2/users/register:\n    post:\n      summary: 用户注册\n      tags: [UserService]\n      requestBody:\n        content:\n          application/json:\n            schema:\n              type: object\n              properties:\n                email: {type: string}\n                password: {type: string}\n      responses:\n        "201":\n          description: 注册成功\n  /api/v2/orders:\n    post:\n      summary: 创建订单\n      tags: [OrderService]\n      responses:\n        "201":\n          description: 订单创建成功',
    attachments:[
      {filename:'architecture_diagram.svg',size:48213,ext:'svg'},
      {filename:'migration_timeline.csv',size:2048,ext:'csv'},
      {filename:'saga_flow.md',size:8192,ext:'md'}
    ]
  }
};

/* ═══ Research report data (REPORT_RESEARCH) ═══ */

export interface ResearchFinding {
  num: string;
  topic: string;
  detail: string;
  sources: string[];
  trace: string;
}

export interface ResearchRecommendation {
  text: string;
  priority: string;
  num: string;
}

export interface ResearchReportData {
  title: string;
  topic: string;
  findings: ResearchFinding[];
  analysis: string[];
  recommendations: ResearchRecommendation[];
  attachments: Attachment[];
}

export const REPORT_RESEARCH: ResearchReportData = {
  title:'微服务架构迁移方案研究',
  topic:'评估单体电商平台微服务化的可行性、路径与风险',
  findings:[
    {num:'01',topic:'绞杀者模式优于大爆炸式重写',detail:'Martin Fowler提出的Strangler Fig模式允许逐步替换单体模块，降低迁移风险。对比大爆炸式重写，绞杀者模式在迁移过程中保持系统始终可运行，且可以在任意阶段暂停。',sources:['martinfowler.com','arxiv:1706.04024'],trace:'intra_team · msg-3'},
    {num:'02',topic:'Saga编排式适合订单-库存场景',detail:'Garcia-Molina 1987经典Saga论文验证了长事务的补偿模式。现代实践中编排式（由订单服务作为协调者）比协调式更适合本场景，因为订单流程有明确的状态机。',sources:['arxiv:1706.04024','microservices.io'],trace:'evidence_check · msg-10'},
    {num:'03',topic:'CDC管道必须在拆分前部署',detail:'Debezium + Kafka Connect的CDC方案可以将数据库变更实时同步到数据湖（Iceberg表格式），使数据消费方（BI、推荐系统）在迁移过程中无感知。',sources:['debezium.io'],trace:'intra_team · msg-6'},
    {num:'04',topic:'Q4旺季是硬约束',detail:'双十一和黑五期间的系统稳定性不可妥协。架构迁移必须在9月底前完成核心链路，并留1个月观察期。否则推迟到次年Q1。',sources:[],trace:'intra_team · msg-7'},
    {num:'05',topic:'Linkerd优于Istio作为初期网格',detail:'Istio功能全面但运维复杂度过高。Linkerd作为轻量替代，在Phase 0足够覆盖mTLS和基本流量管理需求。Phase 2可再评估迁移。',sources:['linkerd.io','owasp.org/ms-top10'],trace:'evidence_check · msg-11'},
  ],
  analysis:[
    '迁移路径选择是核心争议点。架构师主张DDD拆分+三期迁移，工程师补充Saga模式和可观测性要求，安全专家强调mTLS前置。最终方案综合了各方意见，采用绞杀者模式 + 三期迁移 + Phase 0基础设施先行的路径。',
    '数据层是最容易被忽视的风险点。数据工程师指出订单-库存-支付聚合会导致BI和推荐的跨库查询失明。CDC管道的提前部署是关键决策，将数据消费从业务库解耦到数据湖。',
    '安全边界的过渡方案需要分阶段。单体内部调用无鉴权，拆分后需要mTLS + API网关 + 服务间认证。但这些不能一次性引入，否则运维复杂度爆炸。Linkerd先行的折中方案平衡了安全性和可操作性。',
  ],
  recommendations:[
    {text:'Phase 0（4月）优先部署CDC管道 + 可观测性基础设施 + Linkerd服务网格',priority:'P0 · 必须完成',num:'01'},
    {text:'Phase 1（5-7月）拆分用户服务和商品服务，低风险先行',priority:'P0 · 必须完成',num:'02'},
    {text:'Phase 2（8-9月）拆分订单聚合服务 + 支付/库存，核心链路',priority:'P0 · 必须完成',num:'03'},
    {text:'Q4旺季期间冻结架构变更，仅做Bug修复',priority:'P1 · 强烈建议',num:'04'},
    {text:'Phase 3（Q1次年）拆分推荐/营销等边缘服务',priority:'P2 · 计划中',num:'05'},
    {text:'迁移期间冻结DB schema变更，或提前测试DDL兼容矩阵',priority:'P1 · 强烈建议',num:'06'},
  ],
  attachments:[
    {filename:'research_findings.csv',size:4192,ext:'csv'},
    {filename:'evidence_matrix.md',size:6144,ext:'md'},
  ],
};

/* ═══ Business report data (REPORT_BUSINESS) ═══ */

export interface BusinessKpi {
  label: string;
  value: string;
  unit: string;
  trend: string;
}

export interface BusinessRisk {
  level: string;
  desc: string;
}

export interface BusinessTimelineItem {
  date: string;
  text: string;
}

export interface BusinessReportData {
  title: string;
  topic: string;
  execSummary: string;
  kpis: BusinessKpi[];
  marketAnalysis: string[];
  risks: BusinessRisk[];
  timeline: BusinessTimelineItem[];
  nextSteps: string[];
}

export const REPORT_BUSINESS: BusinessReportData = {
  title:'微服务迁移商业分析',
  topic:'单体电商架构微服务化的商业价值、成本与风险评估',
  execSummary:'本次架构迁移预估投入6-9个月，基础设施成本增加约40%。核心收益在于系统可扩展性提升、团队解耦加速迭代、以及Q4旺季的弹性扩容能力。主要风险集中在Q4旺季约束和数据迁移一致性。',
  kpis:[
    {label:'预估投入周期',value:'6-9',unit:'月',trend:'分三期执行'},
    {label:'基础设施成本增幅',value:'40',unit:'%',trend:'云资源+运维人力'},
    {label:'预估年化收益',value:'320',unit:'万',trend:'扩容能力+迭代效率'},
    {label:'迁移风险',value:'中',unit:'',trend:'3项高风险已识别'},
    {label:'Q4影响窗口',value:'2',unit:'周',trend:'冻结期+观察期'},
    {label:'ROI回收期',value:'14',unit:'月',trend:'2027 Q1回本'},
  ],
  marketAnalysis:[
    '电商行业Q4贡献全年GMV的35-45%。双十一和黑五期间的系统稳定性直接关联营收。任何导致服务降级或宕机的架构变更都是不可接受的风险。',
    '微服务架构已成为中大型电商平台的行业标准。阿里、京东、美团均在2-3年内完成了类似迁移。技术债拖延越久，迁移成本越高——单体代码每年增长约15%。',
    '团队规模方面，当前单体由8人团队维护。微服务化后需要拆分为3-4个小队（每队4-6人），总人力需求增至15-20人。这是一项组织变革，不仅是技术变革。',
  ],
  risks:[
    {level:'high',desc:'Q4旺季期间核心链路出现故障，影响双十一GMV。缓解方案：9月底前完成核心链路迁移并留1个月观察期。'},
    {level:'high',desc:'CDC管道DDL兼容性问题导致数据同步中断。缓解方案：迁移期间冻结DB schema变更，提前测试DDL兼容矩阵。'},
    {level:'high',desc:'服务间认证从无到有，过渡期可能出现鉴权遗漏。缓解方案：mTLS纳入Phase 0，API网关统一入口。'},
    {level:'mid',desc:'迁移期间营销系统功能迭代受阻，影响Q3-Q4活动节奏。缓解方案：新老并行开发，BFF层保证接口兼容。'},
    {level:'mid',desc:'基础设施成本超预算（预估+40%可能偏差±10%）。缓解方案：分阶段扩容，监控月度成本。'},
    {level:'low',desc:'团队学习曲线导致初期效率下降。缓解方案：Phase 0期间安排微服务技术培训。'},
  ],
  timeline:[
    {date:'2026-04',text:'Phase 0 启动：CDC + 可观测性 + Linkerd'},
    {date:'2026-05',text:'Phase 1 开始：用户服务 + 商品服务拆分'},
    {date:'2026-07',text:'Phase 1 完成，进入观察期'},
    {date:'2026-08',text:'Phase 2 开始：订单聚合 + 支付/库存'},
    {date:'2026-09',text:'Phase 2 完成，核心链路迁移结束'},
    {date:'2026-10',text:'Q4 冻结期，仅Bug修复'},
    {date:'2027-01',text:'Phase 3 开始：推荐/营销等边缘服务'},
    {date:'2027-03',text:'Phase 3 完成，迁移全部结束'},
  ],
  nextSteps:[
    '确认迁移预算和团队扩招计划（需新增7-12人）',
    '与业务团队确认Q3-Q4功能冻结窗口',
    '启动Phase 0基础设施建设',
    '安排微服务技术培训（DDD、Saga、K8s）',
  ],
};

/* ═══ Comprehensive report data (REPORT_COMPREHENSIVE) ═══ */

export interface SystemDesignComponent {
  component: string;
  desc: string;
  tech: string;
}

export interface DataModelEntity {
  entity: string;
  fields: string[];
}

export interface ComprehensiveReportData {
  title: string;
  topic: string;
  requirements: string[];
  systemDesign: SystemDesignComponent[];
  dataModel: DataModelEntity[];
  apiSpec: string;
  attachments: Attachment[];
}

export const REPORT_COMPREHENSIVE: ComprehensiveReportData = {
  title:'电商平台微服务架构 — 综合设计文档',
  topic:'需求 + 系统设计 + API + 数据模型的完整产出',
  requirements:[
    '用户服务：认证（OAuth2）、Profile管理、权限控制（RBAC）',
    '商品服务：Catalog管理、搜索（ES）、详情页',
    '订单服务：创建、支付、取消、退款，Saga编排',
    '库存服务：扣减、预占、回滚',
    '推荐服务：基于用户行为的实时推荐',
    '营销服务：优惠券、秒杀、拼团',
  ],
  systemDesign:[
    {component:'API网关',desc:'Kong/APISIX，统一入口，认证、限流、WAF',tech:'Kong 3.x'},
    {component:'服务网格',desc:'mTLS + 流量管理 + 可观测性',tech:'Linkerd 2.x（Phase 0）'},
    {component:'消息队列',desc:'异步解耦，事件驱动',tech:'Kafka 3.x'},
    {component:'CDC管道',desc:'数据库变更实时同步到数据湖',tech:'Debezium + Kafka Connect + Iceberg'},
    {component:'可观测性',desc:'追踪 + 日志 + 指标',tech:'OpenTelemetry + ELK + Prometheus'},
    {component:'CI/CD',desc:'多服务独立pipeline',tech:'GitLab CI + Helm + K8s'},
  ],
  dataModel:[
    {entity:'users',fields:['id [PK]','email','password_hash','role','created_at']},
    {entity:'products',fields:['id [PK]','name','price','stock','category_id [FK]','status']},
    {entity:'orders',fields:['id [PK]','user_id [FK]','total_amount','status','created_at','updated_at']},
    {entity:'order_items',fields:['id [PK]','order_id [FK]','product_id [FK]','quantity','unit_price']},
    {entity:'payments',fields:['id [PK]','order_id [FK]','amount','method','status','paid_at']},
    {entity:'inventory',fields:['id [PK]','product_id [FK]','available','locked','version']},
  ],
  apiSpec:'openapi: 3.0.0\ninfo:\n  title: E-Commerce Microservices API\n  version: "2.0"\npaths:\n  /api/v2/users/register:\n    post:\n      summary: 用户注册\n      responses:\n        "201": {description: 注册成功}\n  /api/v2/products/{id}:\n    get:\n      summary: 商品详情\n      parameters:\n        - name: id\n          in: path\n          required: true\n          schema: {type: integer}\n      responses:\n        "200": {description: 商品详情}\n  /api/v2/orders:\n    post:\n      summary: 创建订单\n      responses:\n        "201": {description: 订单创建成功}\n  /api/v2/orders/{id}/pay:\n    post:\n      summary: 支付订单\n      responses:\n        "200": {description: 支付成功}\n  /api/v2/inventory/deduct:\n    put:\n      summary: 扣减库存\n      responses:\n        "200": {description: 扣减成功}',
  attachments:[
    {filename:'system_design.svg',size:52300,ext:'svg'},
    {filename:'data_model.sql',size:12288,ext:'sql'},
    {filename:'api_spec.yaml',size:8192,ext:'yaml'},
  ],
};

/* ═══ Deployable service data (REPORT_DEPLOYABLE) ═══ */

export interface FileTreeNode {
  type: string;
  name: string;
  indent: number;
}

export interface TestResult {
  name: string;
  result: string;
  time: string;
}

export interface DeployablePrd {
  title: string;
  goal: string;
  scope: string;
  endpoints: string[];
}

export interface DeployableReportData {
  title: string;
  topic: string;
  deployStatus: string;
  deployUrl: string;
  deployTime: string;
  reviewResult: string;
  fileTree: FileTreeNode[];
  tests: TestResult[];
  prd: DeployablePrd;
  dockerfile: string;
}

export const REPORT_DEPLOYABLE: DeployableReportData = {
  title:'用户服务 — 可部署微服务',
  topic:'含PRD + OpenAPI + 完整代码 + Docker部署 + pytest测试',
  deployStatus:'healthy',
  deployUrl:'http://user-service.conclave-sandbox:8080/health',
  deployTime:'2026-07-16 15:06:42',
  reviewResult:'通过',
  fileTree:[
    {type:'dir',name:'user-service/',indent:0},
    {type:'file',name:'main.py',indent:1},
    {type:'file',name:'models.py',indent:1},
    {type:'file',name:'auth.py',indent:1},
    {type:'file',name:'requirements.txt',indent:1},
    {type:'dir',name:'tests/',indent:1},
    {type:'file',name:'test_auth.py',indent:2},
    {type:'file',name:'test_models.py',indent:2},
    {type:'file',name:'Dockerfile',indent:1},
    {type:'file',name:'docker-compose.yml',indent:1},
  ],
  tests:[
    {name:'test_register_success',result:'pass',time:'0.03s'},
    {name:'test_register_duplicate_email',result:'pass',time:'0.02s'},
    {name:'test_login_success',result:'pass',time:'0.04s'},
    {name:'test_login_wrong_password',result:'pass',time:'0.02s'},
    {name:'test_token_validation',result:'pass',time:'0.05s'},
    {name:'test_token_expired',result:'pass',time:'0.03s'},
  ],
  prd:{
    title:'用户服务 PRD',
    goal:'提供用户注册、登录、Token验证功能，支持OAuth2认证和RBAC权限控制。',
    scope:'认证、Profile管理、权限控制。不含用户画像和推荐功能。',
    endpoints:['POST /api/v2/users/register','POST /api/v2/users/login','GET /api/v2/users/me','POST /api/v2/users/logout'],
  },
  dockerfile:'FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY . .\nEXPOSE 8080\nCMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]',
};

/* ═══ Report types registry (REPORT_TYPES) ═══ */

export const REPORT_TYPES: ReportType[] = [
  {id:'prd_openapi',label:'PRD + OpenAPI'},
  {id:'research_report',label:'研究报告'},
  {id:'business_report',label:'商业分析'},
  {id:'comprehensive',label:'综合文档'},
  {id:'design_doc',label:'设计文档'},
  {id:'code_analysis',label:'代码分析'},
  {id:'data_science',label:'数据科学'},
  {id:'tested_system',label:'测试系统'},
  {id:'deployable_service',label:'可部署服务'},
];
