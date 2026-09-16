# Conclave 工业级服务生成能力升级报告

**日期**: 2026-07-18
**背景**: 对Conclave的可部署服务生成能力进行全面评估和升级，从demo级单文件生成升级为工业级分层项目生成。

## 一、问题诊断（升级前）

### 1.1 核心问题
- **单文件生成模式**: 生成单个`app.py`(20KB)，容易产出demo级代码
- **Bugfix阶段LLM超时**: 大prompt+逐个问题修复导致连续ReadTimeout，修复完全失效
- **Dockerfile HEALTHCHECK缺curl**: 健康检查必失败
- **静态文件缺失**: 代码引用`/static/style.css`但未生成
- **代码审查误报**: 将参数化查询误判为SQL注入
- **部署失败无详情**: 只返回ok/false，无错误日志
- **前端UI状态不同步**: 后端DONE但前端显示"进行中"

### 1.2 架构性缺陷
- 无断点续传：阶段失败直接标记FAILED，无法从断点恢复
- 无自我迭代：产出质量不达标时无法自动改进
- 无测试驱动：部署后不运行测试，无法验证功能正确性
- 无demo检测：无法识别"实现了功能但只是个demo"的情况
- 无跨会议演进：每次从头生成，无法基于历史版本扩展
- 质量门禁简陋：仅靠功能覆盖度检查，无法判断规模和真实性

## 二、本次优化内容

### Commit 1: P0 Bug修复
- 修复PlaywrightWebSearch session_key重复参数bug
- 修复bugfix阶段LLM超时：改为按文件批量修复，精简prompt
- 修复Dockerfile curl缺失：自动检测并补全HEALTHCHECK依赖
- 修复静态CSS缺失：自动生成默认CSS
- 修复requirements.txt缺依赖：自动补全pydantic
- 修复代码审查误报：优化CODE_REVIEW_PROMPT，明确参数化查询是正确的
- 修复部署错误无详情：增加traceback记录和logs输出

### Commit 2: 断点续传 + 自我迭代 + 跨会议演进
- **断点续传**:
  - 阶段级自动重试（默认2次，可配置max_stage_retries）
  - Checkpoint记录：每阶段成功/失败都记录
  - FAILED状态支持resume：从失败阶段重新执行
  - 新增MeetingState字段：checkpoint, stage_retry_count, max_stage_retries
- **自我迭代Loop**:
  - 质量门禁评估后不达标自动触发迭代
  - 质量反馈注入produce prompt
  - 迭代历史记录（iteration_history）
  - 新增API参数：auto_iterate, max_iterations
- **跨会议演进**:
  - 加载reference_meeting_ids的项目文件作为baseline
  - 注入关键文件内容到prompt，引导"扩展而非重写"

### Commit 3: 工业级分层架构生成
- **DeployableServiceArtifact重构**:
  - 新增project_tree: 后端完整文件树
  - 新增frontend_tree: React前端文件树
  - 新增test_tree: pytest测试文件树
  - 新增root_files: 部署配置文件
  - 新增complexity_level: micro/small/medium/large
  - 新增tech_stack, title, description等元数据
  - 向后兼容旧的app_code/dockerfile单文件模式
  - 新增get_effective_tree/count_code_lines/count_files方法
- **PRODUCE_DEPLOYABLE_SERVICE prompt重写**:
  - 第一步：复杂度评估（根据需求决定生成规模）
  - 第二步：强制分层架构（routers/schemas/services/dao/db/domain/config）
  - React 18 + TypeScript + Vite前端要求
  - pytest + pytest-asyncio + httpx测试要求
  - 明确禁止demo/stub/hardcoded mock
  - 17条代码质量硬性要求
- **produce.py重构**:
  - 支持project_tree完整目录树写入
  - 安全路径处理（防路径穿越）
  - 自动补全__init__.py、/health端点
  - 语法检查（ast.parse所有Python文件）
  - 文件数/代码行数统计
  - 跨会议baseline代码加载

### Commit 4: 质量门禁升级（8维度评估）
| 维度 | 权重 | 硬门槛 | 检测方式 |
|------|------|--------|---------|
| 部署成功 | 10分 | 必须通过 | Docker健康检查 |
| 测试通过 | 15分 | 有测试必须全过 | 容器内pytest执行 |
| 架构完整性 | 25分 | - | 检查11个关键层次文件 |
| 代码规模匹配 | 20分 | 文件/行数必须匹配复杂度 | 防止demo(<200行/<5文件判为stub) |
| 功能真实性 | 15分 | - | 检测TODO/NotImplemented/return[]等demo模式 |
| 代码质量 | 15分 | 无语法错误 | ast.parse+错误处理检查 |
| 前端完整性 | 10分 | medium+必须有React | 检查package.json/App.tsx/components |
| 文档完整性 | 5分 | - | README+.env.example存在性 |

- **硬失败机制**: 任一硬门槛未通过即触发迭代
- **Demo检测**: 文件<5或代码<200行或>=3处demo标记→判为stub
- **is_demo_suspected标记**: 返回给前端展示

### Commit 5: 测试驱动 + 沙箱测试执行
- **sandbox.py新增run_tests_in_container()**:
  - 在已部署容器内执行pytest
  - 自动安装pytest/pytest-asyncio/httpx
  - 解析测试结果（passed/failed/failures列表）
  - 返回结构化测试结果
- **produce节点集成测试执行**:
  - 部署成功+有测试文件时自动运行测试
  - 测试失败用例名注入下一轮迭代
  - 测试不通过=质量不达标=必须迭代
- **审计日志模块** (observability/audit.py):
  - 安全事件审计记录
- **前端UI组件** (Toast/ConfirmModal/ErrorBoundary):
  - 基础交互组件

## 三、架构标准（生成代码必须遵循）

参照Conclave自身的分层架构，定义标准项目结构：

```
{project}/
├── app/
│   ├── main.py              # create_app()工厂 + lifespan
│   ├── config.py            # @dataclass(frozen=True) Settings
│   ├── middleware.py        # CORS/认证/追踪
│   ├── dependencies.py      # FastAPI依赖注入
│   ├── routers/             # Controller层（APIRouter按资源拆分）
│   ├── schemas/             # DTO/VO层（Pydantic v2）
│   ├── services/            # BO层（业务逻辑）
│   ├── dao/                 # DAO层（数据访问）
│   ├── db/
│   │   ├── base.py          # SQLAlchemy Base
│   │   ├── engine.py        # async_engine + session_factory
│   │   └── models/          # DO层（ORM模型）
│   └── domain/              # 领域层（枚举/纯业务规则）
├── frontend/                # React 18 + TypeScript + Vite
│   ├── Dockerfile           # node builder → nginx两阶段
│   ├── nginx.conf
│   └── src/
│       ├── components/
│       ├── pages/
│       ├── hooks/
│       ├── lib/api.ts
│       ├── store/           # React Context
│       └── styles/
├── tests/                   # pytest
│   ├── conftest.py
│   └── test_*.py
├── alembic/                 # 数据库迁移
├── Dockerfile               # 多阶段构建
├── docker-compose.yml
├── requirements.txt
├── pyproject.toml
├── .env.example
└── README.md
```

## 四、复杂度等级定义

| 等级 | 文件数 | 代码行数 | 架构要求 | 前端 | 测试 | 数据库 |
|------|--------|---------|---------|------|------|--------|
| micro | <10 | 100-500 | 单文件FastAPI | 无 | 无 | SQLite |
| small | 10-20 | 300-2000 | 基础分层 | 简单HTML | 基础 | SQLite |
| medium | 20-50 | 1000-8000 | 完整7层 | React+TS | pytest | PostgreSQL |
| large | 50+ | 3000+ | 多模块/微服务 | React+TS | 完整测试 | PG+Redis |

## 五、待完成的下一步优化（P0优先级）

### 5.1 分阶段生成（最紧迫）
当前单次LLM调用生成20-50个文件极易截断，需要改为：
1. 架构规划阶段：输出项目结构、类图、模块划分
2. 骨架生成阶段：生成配置文件、数据库模型、基础框架
3. 逐模块填充：每次生成1-2个模块的代码（routers/schemas/dao/services）
4. 测试生成：基于API设计生成测试用例
5. 部署配置生成：Dockerfile/docker-compose等

### 5.2 增量修复
- 迭代时不重新生成整个项目，只修改测试失败/有问题的文件
- 基于diff的patch模式输出

### 5.3 容器构建鲁棒性
- npm/pip使用lock文件固定版本
- 构建超时自动重试
- 完整构建日志记录

### 5.4 前端UI升级
- 引入轻量UI组件库（shadcn/ui或Headless UI）
- 产出物查看器专业化（代码用Monaco Editor、报告用专业排版）
- 暗色主题优化、响应式适配

### 5.5 数据源接入
- 代码生成：GitHub模板few-shot
- 商业调研：Tavily/SerpAPI专业搜索
- 金融分析：AKShare开源财经数据

## 六、测试验证

本次优化后需要验证的场景：
1. [ ] micro复杂度：单文件工具生成+部署成功
2. [ ] small复杂度：基础分层服务生成+部署
3. [ ] medium复杂度：完整React+PG+pytest项目生成+部署+测试通过
4. [ ] 断点续传：中途杀掉进程后resume恢复
5. [ ] 自我迭代：故意制造低质量产出，验证auto_iterate能改进
6. [ ] 跨会议演进：基于已有会议产出扩展新功能
7. [ ] Demo检测：生成<200行代码时质量门禁判为不达标
