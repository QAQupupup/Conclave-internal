# 分阶段服务生成管线（Phased Generation Pipeline）
#
# 解决核心问题：单次LLM调用生成20-50个文件的完整项目，超出模型输出可靠性范围，
# 导致截断、幻觉、超时。改为管线式分阶段生成，每次LLM调用只输出2-5个聚焦文件。
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.agents.compute import ThinkRequest, execute_think
from app.models import MeetingState, Role

logger = logging.getLogger(__name__)


@dataclass
class ModuleDef:
    """模块定义"""
    name: str
    resource: str
    description: str = ""
    has_crud: bool = True
    api_endpoints: list[str] = field(default_factory=list)
    data_fields: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ArchitecturePlan:
    """Phase 1 输出：架构规划"""
    title: str = ""
    description: str = ""
    complexity_level: str = "medium"
    tech_stack: list[str] = field(default_factory=list)
    port: int = 8000
    modules: list[ModuleDef] = field(default_factory=list)
    needs_frontend: bool = True
    needs_database: bool = True
    db_type: str = "postgresql"
    has_auth: bool = False
    run_command: str = "uvicorn app.main:app --host 0.0.0.0 --port 8000"


@dataclass
class PhasedGenerationResult:
    """分阶段生成最终结果，与 DeployableServiceArtifact 结构兼容"""
    title: str = ""
    description: str = ""
    complexity_level: str = "medium"
    tech_stack: list[str] = field(default_factory=list)
    port: int = 8000
    run_command: str = "uvicorn app.main:app --host 0.0.0.0 --port 8000"
    credentials: dict[str, str] = field(default_factory=dict)
    project_tree: dict[str, str] = field(default_factory=dict)
    frontend_tree: dict[str, str] = field(default_factory=dict)
    test_tree: dict[str, str] = field(default_factory=dict)
    root_files: dict[str, str] = field(default_factory=dict)
    prd: dict[str, Any] = field(default_factory=dict)
    openapi: str = ""
    phases_executed: list[str] = field(default_factory=list)
    total_llm_calls: int = 0
    errors: list[str] = field(default_factory=list)

    def to_result_dict(self) -> dict[str, Any]:
        """转换为与原有ProduceResult兼容的dict，供下游部署流程使用"""
        import json
        # 合并所有代码文件：后端 + 前端 + 测试 + 根目录文件
        all_files: dict[str, str] = {}
        all_files.update(self.project_tree)
        all_files.update(self.frontend_tree)
        all_files.update(self.test_tree)
        all_files.update(self.root_files)

        # 提取关键文件
        dockerfile = all_files.get("Dockerfile", "")
        docker_compose = all_files.get("docker-compose.yml", "")
        requirements = all_files.get("requirements.txt", "")
        readme = all_files.get("README.md", "")
        main_py = all_files.get("app/main.py", all_files.get("main.py", ""))

        # 构建file_tree用于旧版查看器
        file_tree = self._build_file_tree_list(all_files)

        return {
            "prd": self.prd,
            "openapi": self.openapi,
            "deployable_service": {
                "title": self.title,
                "description": self.description,
                "complexity_level": self.complexity_level,
                "tech_stack": self.tech_stack,
                "port": self.port,
                "run_command": self.run_command,
                "credentials": self.credentials,
                "file_tree": file_tree,
                "project_tree": self.project_tree,
                "frontend_tree": self.frontend_tree,
                "test_tree": self.test_tree,
                "root_files": self.root_files,
                "app_code": json.dumps(all_files, ensure_ascii=False),
                "dockerfile": dockerfile,
                "docker_compose": docker_compose,
                "requirements_txt": requirements,
                "readme": readme,
                "main_py": main_py,
                "static_files": all_files,
                "modules": [
                    {"name": m.name, "resource": m.resource, "api_endpoints": m.api_endpoints}
                    for m in self.plan.modules
                ] if getattr(self, 'plan', None) else [],
                "phased_generation": {
                    "total_llm_calls": self.total_llm_calls,
                    "phases_executed": self.phases_executed,
                    "file_count": len(all_files),
                    "backend_file_count": len(self.project_tree),
                    "frontend_file_count": len(self.frontend_tree),
                    "test_file_count": len(self.test_tree),
                },
            }
        }

    @staticmethod
    def _build_file_tree_list(files: dict[str, str]) -> list[dict]:
        """将{path: content}转换为旧版file_tree [{name, type, indent}]格式"""
        items = []
        dirs_added = set()
        for path in sorted(files.keys()):
            parts = path.split("/")
            for i in range(len(parts) - 1):
                dir_path = "/".join(parts[:i+1])
                if dir_path not in dirs_added:
                    dirs_added.add(dir_path)
                    items.append({"name": parts[i], "type": "dir", "indent": i})
            fname = parts[-1]
            items.append({"name": fname, "type": "file", "indent": len(parts) - 1})
        return items


async def _call_llm(prompt: str, schema_hint: str,
                    state: MeetingState, temperature: float = 0.1) -> dict[str, Any]:
    """统一LLM调用封装"""
    from app.agents.compute import _inject_profile, _inject_skills
    prompt = _inject_profile(prompt, Role.ENGINEER.value)
    prompt = _inject_skills(prompt, stage="produce",
                            deliverable_type="deployable_service",
                            role=Role.ENGINEER.value)
    req = ThinkRequest(
        meeting_id=state.meeting_id,
        agent_role=Role.ENGINEER.value, stage="produce",
        prompt=prompt, schema_hint=schema_hint,
        temperature=temperature, seed=42,
    )
    resp = await execute_think(req)
    if not resp.success:
        logger.warning(f"PhasedGen LLM failed ({schema_hint}): {resp.error}")
        return {"_error": resp.error}
    return resp.result


def _phase1_prompt(topic: str, decision_record: dict, quality_feedback: str) -> str:
    fb = f"\n\n[质量迭代反馈]\n{quality_feedback}\n" if quality_feedback else ""
    return f"""[分阶段生成 Phase 1/7: 架构规划]

你是资深系统架构师。为以下需求做架构设计，不写代码。

【需求】{topic}
【讨论结论】{str(decision_record)[:2000]}
{fb}

【任务】评估复杂度，划分模块，确定技术栈。
复杂度: micro(<10文件单文件)/small(10-20基础分层)/medium(20-50完整7层+React+PG+测试,默认)/large(50+多模块)

【强制分层(medium+)】app/{{main,config,middleware,dependencies}}.py + app/{{routers,schemas,services,dao,db/models,domain}}/

输出JSON:
{{
  "title": "服务英文名(如url-shortener)",
  "description": "一句话描述",
  "complexity_level": "medium",
  "tech_stack": ["FastAPI","SQLAlchemy","asyncpg","PostgreSQL","Pydantic","Uvicorn"],
  "port": 8000,
  "needs_frontend": true,
  "needs_database": true,
  "db_type": "postgresql",
  "has_auth": false,
  "modules": [{{
    "name": "模块英文名", "resource": "url资源段",
    "description": "职责", "has_crud": true,
    "api_endpoints": ["POST /api/v1/...","GET /api/v1/..."],
    "data_fields": [{{"name":"id","type":"int","required":true,"description":"主键"}}]
  }}]
}}"""


def _phase2_prompt(plan: ArchitecturePlan) -> str:
    mods = "\n".join(
        f"- {m.name}({m.resource}): {m.description}; APIs: {', '.join(m.api_endpoints[:6])}"
        for m in plan.modules
    )
    return f"""[分阶段生成 Phase 2/7: OpenAPI规范+PRD]

基于架构规划生成OpenAPI 3.0 YAML和PRD摘要。

【项目】{plan.title} - {plan.description}
【复杂度】{plan.complexity_level}  【端口】{plan.port}  【认证】{plan.has_auth}
【模块】
{mods}

【要求】
- API路径统一/api/v1开头
- 每个端点含summary/requestBody/responses(200/400/404/422/500)
- Schema用$ref引用components/schemas
- 分页返回{{items,total,page,size}}
- 错误响应{{detail:"描述"}}

输出JSON:
{{
  "prd": {{"title":"{plan.title}","goal":"目标","scope":"范围","assumptions":[],"constraints":[],"api_endpoints":[],"open_questions":[]}},
  "openapi": "openapi: 3.0.0\\ninfo:\\n  title: ...\\npaths:\\n...\\ncomponents:\\n  schemas:\\n..."
}}
openapi为完整YAML字符串(\\n换行)。输出严格JSON。"""


def _phase3_prompt(plan: ArchitecturePlan, openapi_spec: str) -> str:
    if plan.complexity_level == "micro":
        return "{}"
    return f"""[分阶段生成 Phase 3/7: 测试用例(TDD)]

基于API规范生成pytest测试。

【项目】{plan.title} 【端口】{plan.port} 【DB】{plan.db_type}
【OpenAPI】{openapi_spec[:4000]}

【要求】
1. conftest.py: asyncio event loop fixture(scope=session), httpx.AsyncClient+ASGITransport,
   SQLite内存测试DB, dependency override get_db, 建表/清理fixture
2. 每模块test_{{module}}.py: 每端点≥3测试(成功/校验失败/不存在)
3. 命名test_{{feature}}_{{scenario}}
4. 用aiosqlite，禁止assert True空测试

输出JSON: {{"files": {{"tests/conftest.py":"完整代码","tests/test_xxx.py":"..."}}}}"""


def _phase4_prompt(plan: ArchitecturePlan) -> str:
    return f"""[分阶段生成 Phase 4/7: 项目骨架]

生成基础设施文件，不写业务逻辑。

【项目】{plan.title} - {plan.description}
【复杂度】{plan.complexity_level}  【栈】{', '.join(plan.tech_stack)}
【端口】{plan.port}  【DB】{plan.db_type}  【认证】{plan.has_auth}  【前端】{plan.needs_frontend}

【需要生成】
1. app/config.py: @dataclass(frozen=True) Settings, 环境变量读取, DATABASE_URL默认sqlite+aiosqlite
2. app/main.py: create_app()工厂+lifespan, CORS, 注册routers(try/except ImportError容错), /health端点
3. app/middleware.py: CORS+请求日志中间件
4. app/dependencies.py: get_db依赖注入(yield async session)
5. app/db/base.py: SQLAlchemy DeclarativeBase, TimestampMixin(created_at/updated_at)
6. app/db/engine.py: create_async_engine+async_session_factory+init_db
7. app/domain/enums.py: 通用str,Enum基类
8. requirements.txt: 依赖分组注释，版本>=，含fastapi/sqlalchemy/uvicorn/pydantic-settings/aiosqlite
9. pyproject.toml: pytest配置asyncio_mode=auto
10. Dockerfile: 多阶段(swr国内基础镜像+清华pip+安装curl+HEALTHCHECK+uvicorn 0.0.0.0)
11. .env.example: 环境变量模板
12. README.md: 功能/栈/启动/API/环境变量

输出JSON: {{"files": {{"app/config.py":"...","app/main.py":"...",...}}}} 每文件完整无省略。"""


def _phase5_module_prompt(plan: ArchitecturePlan, module: ModuleDef,
                          existing: dict[str, str], is_first: bool) -> str:
    ctx_keys = ("app/db/base.py", "app/db/engine.py", "app/config.py", "app/dependencies.py")
    ctx = "\n\n".join(f"=== {k} ===\n{existing[k][:1200]}" for k in ctx_keys if k in existing)
    extra = """
【首个模块额外生成】app/db/models/__init__.py(re-export所有模型), app/schemas/common.py(PageResponse)""" if is_first else ""
    fields = "\n".join(f"  - {f['name']}({f['type']}): {f.get('description','')}" for f in module.data_fields)
    return f"""[分阶段生成 Phase 5/7: 后端模块 - {module.name}]

只生成当前模块代码。

【模块】{module.name} /{module.resource}: {module.description}
【API】{', '.join(module.api_endpoints)}
【字段】
{fields}
{extra}

【生成5个文件】
1. app/schemas/{module.name}.py: Pydantic v2 schemas(XxxCreate/XxxUpdate/XxxResponse), model_config=ConfigDict(from_attributes=True), Field(description=...)
2. app/db/models/{module.name}.py: SQLAlchemy 2.0模型(Base+TimestampMixin), Mapped[mapped_column]
3. app/dao/{module.name}_dao.py: async CRUD(async with session.begin()), 参数化查询, commit/rollback
4. app/services/{module.name}_service.py: 业务逻辑层
5. app/routers/{module.name}.py: APIRouter(prefix="/api/v1/{module.resource}"), 依赖注入service, HTTPException(404)

【质量要求】参数化查询(:param)、分页(skip/limit)、import路径正确(from app.db.base import Base)、列表返回PageResponse

输出JSON: {{"files": {{"app/schemas/{module.name}.py":"...","app/db/models/{module.name}.py":"...","app/dao/{module.name}_dao.py":"...","app/services/{module.name}_service.py":"...","app/routers/{module.name}.py":"..."}}}}"""


def _phase6_fe_scaffold_prompt(plan: ArchitecturePlan) -> str:
    if plan.complexity_level in ("micro","small") or not plan.needs_frontend:
        return "{}"
    return f"""[分阶段生成 Phase 6/7a: 前端骨架]

为 {plan.title} 生成React前端基础设施。

【要求】
- React 18+TypeScript+Vite
- nginx.conf: /api反代http://backend:8000, SPA fallback
- frontend/Dockerfile: node:20-slim构建→nginx:1.27-alpine托管, npm用npmmirror
- package.json含依赖: react, react-dom, react-router-dom, typescript, @types/*, vite
- App.tsx含路由和基本布局
- main.tsx入口
- 简洁美观UI(参考Linear/Notion风格)

输出JSON: {{"files": {{
  "frontend/package.json":"...",
  "frontend/vite.config.ts":"...",
  "frontend/tsconfig.json":"...",
  "frontend/index.html":"...",
  "frontend/Dockerfile":"...",
  "frontend/nginx.conf":"...",
  "frontend/src/main.tsx":"...",
  "frontend/src/App.tsx":"...",
  "frontend/src/vite-env.d.ts":"..."
}}}}"""


def _phase6_fe_code_prompt(plan: ArchitecturePlan, openapi_spec: str) -> str:
    if plan.complexity_level in ("micro","small") or not plan.needs_frontend:
        return "{}"
    return f"""[分阶段生成 Phase 6/7b: 前端业务代码]

为 {plan.title} 生成前端业务代码。

【API】{openapi_spec[:3000]}

【生成】
1. frontend/src/types/index.ts - TypeScript类型定义(对应API schema)
2. frontend/src/lib/api.ts - fetch封装(baseURL=/api, 统一错误处理)
3. frontend/src/store/index.tsx - React Context+useReducer状态管理
4. frontend/src/styles/tokens.css - CSS变量(颜色/间距/圆角/字体)
5. frontend/src/styles/components.css - 组件样式(Notion/Linear风格)
6. frontend/src/components/Layout.tsx - 布局组件(导航栏+主内容区)
7. frontend/src/components/Loading.tsx - 加载状态
8. frontend/src/components/ErrorMessage.tsx - 错误展示
9. frontend/src/pages/HomePage.tsx - 首页/列表页
10. frontend/src/pages/DetailPage.tsx - 详情/编辑页(如有)

输出JSON: {{"files": {{...}}}} 每文件完整TSX/CSS。"""


def _phase7_integrate_prompt(plan: ArchitecturePlan,
                            existing: dict[str, str]) -> dict[str, str]:
    """Phase 7: 整合 - 补全docker-compose.yml和routers/__init__.py，返回{path: content}"""
    has_frontend = plan.needs_frontend and plan.complexity_level not in ("micro","small")

    routers_import = "\n".join(
        f"from app.routers.{m.name} import router as {m.name}_router"
        for m in plan.modules
    )

    # 构建docker-compose（避免f-string中复杂条件）
    compose_lines = [
        "version: '3.8'",
        "services:",
        "  backend:",
        "    build: .",
        f"    ports: [\"{plan.port}:{plan.port}\"]",
        "    environment:",
        "      - DATABASE_URL=postgresql+asyncpg://conclave:conclave@db:5432/conclave",
        "      - SECRET_KEY=dev-change-me",
        "    depends_on:",
        "      db:",
        "        condition: service_healthy",
        "    restart: unless-stopped",
    ]
    if has_frontend:
        compose_lines += [
            "  frontend:",
            "    build: ./frontend",
            "    ports: ['80:80']",
            "    depends_on: [backend]",
        ]
    compose_lines += [
        "  db:",
        "    image: swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/postgres:16-alpine",
        "    environment:",
        "      POSTGRES_USER: conclave",
        "      POSTGRES_PASSWORD: conclave",
        "      POSTGRES_DB: conclave",
        "    volumes: [\"pgdata:/var/lib/postgresql/data\"]",
        "    healthcheck:",
        '      test: ["CMD-SHELL", "pg_isready -U conclave"]',
        "      interval: 5s",
        "      retries: 5",
        "volumes:",
        "  pgdata:",
    ]
    compose = "\n".join(compose_lines)

    routers_init = f"""# Auto-generated routers init
{routers_import}

__all__ = [{', '.join(f'"{m.name}_router"' for m in plan.modules)}]
"""

    # 检查main.py是否include了routers
    main_py = existing.get("app/main.py", "")
    needs_main_patch = "include_router" not in main_py

    files = {
        "docker-compose.yml": compose,
        "app/routers/__init__.py": routers_init,
    }

    if needs_main_patch and main_py:
        # 在app = create_app()后添加include_router
        patched = main_py.rstrip()
        if "from app.routers import" not in patched:
            patched = patched.replace(
                "from fastapi",
                "from app.routers import " + ", ".join(f"{m.name}_router" for m in plan.modules) + "\nfrom fastapi",
                1
            )
        if "include_router" not in patched:
            patched += "\n\n# Auto-included routers\n"
            for m in plan.modules:
                patched += f"app.include_router({m.name}_router)\n"
        files["app/main.py"] = patched

    # 确保alembic配置(medium+)
    if plan.complexity_level in ("medium", "large") and plan.needs_database:
        files["alembic.ini"] = """[alembic]
script_location = alembic
sqlalchemy.url = postgresql+asyncpg://conclave:conclave@db:5432/conclave

[loggers]
keys = root,sqlalchemy,alembic"""
        files["alembic/env.py"] = """import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app.db.base import Base
from app.db.engine import DATABASE_URL
config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata

def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"),
                      target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(conn):
    context.configure(connection=conn, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as conn:
        await conn.run_sync(do_run_migrations)
    await connectable.dispose()

if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())"""
        files["alembic/versions/0001_initial.py"] = '"""initial schema"""\nfrom alembic import op\nimport sqlalchemy as sa\n\nrevision = "0001"\ndown_revision = None\nbranch_labels = None\ndepends_on = None\n\ndef upgrade():\n    pass  # Auto-generated; run `alembic revision --autogenerate` after model creation\n\ndef downgrade():\n    pass'

    return files


async def generate_deployable_service_phased(
    state: MeetingState,
    on_progress: Any = None,
) -> PhasedGenerationResult:
    """分阶段生成可部署服务（主入口）"""
    result = PhasedGenerationResult()
    llm_calls = 0

    async def _p(step: str, msg: str, pct: int):
        if on_progress:
            try: await on_progress(step, msg, pct)
            except Exception: pass

    topic = state.clarified_topic or state.topic or "generated-service"
    decision_record = state.decision_record or {}
    qf = state.quality_feedback if state.iteration_count > 0 else ""

    # Phase 1: 架构规划
    await _p("phase1", "Phase 1/7: 架构规划...", 5)
    r = await _call_llm(_phase1_prompt(topic, decision_record, qf), "phased_plan", state)
    llm_calls += 1
    if "_error" in r:
        result.errors.append(f"Phase1: {r['_error']}")
        return result

    plan = ArchitecturePlan(
        title=r.get("title","generated-service"), description=r.get("description",""),
        complexity_level=r.get("complexity_level","medium"),
        tech_stack=r.get("tech_stack",["FastAPI","SQLAlchemy","PostgreSQL"]),
        port=int(r.get("port",8000)),
        needs_frontend=r.get("needs_frontend",True),
        needs_database=r.get("needs_database",True),
        db_type=r.get("db_type","postgresql"),
        has_auth=r.get("has_auth",False),
    )
    for m in r.get("modules",[]):
        plan.modules.append(ModuleDef(
            name=m.get("name","items"), resource=m.get("resource","items"),
            description=m.get("description",""), has_crud=m.get("has_crud",True),
            api_endpoints=m.get("api_endpoints",[]), data_fields=m.get("data_fields",[]),
        ))
    if not plan.modules:
        plan.modules.append(ModuleDef("items","items","主资源",True,
            ["GET /api/v1/items","POST /api/v1/items","GET /api/v1/items/{id}",
             "PUT /api/v1/items/{id}","DELETE /api/v1/items/{id}"],
            [{"name":"id","type":"int","required":True,"description":"主键"},
             {"name":"name","type":"str","required":True,"description":"名称"}]))

    result.title=plan.title; result.description=plan.description
    result.complexity_level=plan.complexity_level
    result.tech_stack=plan.tech_stack; result.port=plan.port
    result.run_command=plan.run_command
    result.plan = plan  # 保存完整plan供to_result_dict使用
    result.phases_executed.append("plan")
    await _p("phase1_done", f"架构规划完成: {plan.complexity_level}, {len(plan.modules)}模块", 14)

    # Phase 2: API规范+PRD
    await _p("phase2", "Phase 2/7: OpenAPI+PRD...", 18)
    r = await _call_llm(_phase2_prompt(plan), "phased_specs", state)
    llm_calls += 1
    if "_error" not in r:
        result.prd = r.get("prd", {"title": plan.title})
        result.openapi = r.get("openapi", "")
    else:
        result.errors.append(f"Phase2: {r['_error']}")
        result.prd = {"title": plan.title}
    result.phases_executed.append("specs")
    await _p("phase2_done", "API规范完成", 26)

    # Phase 3: 测试
    await _p("phase3", "Phase 3/7: 测试用例...", 28)
    if plan.complexity_level != "micro":
        r = await _call_llm(_phase3_prompt(plan, result.openapi), "phased_tests", state)
        llm_calls += 1
        if "_error" not in r:
            for p,c in r.get("files",{}).items():
                if isinstance(c,str) and len(c)>10: result.test_tree[p]=c
        else:
            result.errors.append(f"Phase3: {r['_error']}")
    result.phases_executed.append("tests")
    await _p("phase3_done", f"测试完成: {len(result.test_tree)}文件", 35)

    # Phase 4: 骨架
    await _p("phase4", "Phase 4/7: 项目骨架...", 38)
    r = await _call_llm(_phase4_prompt(plan), "phased_scaffold", state)
    llm_calls += 1
    scaffold_files = {}
    if "_error" not in r:
        for p,c in r.get("files",{}).items():
            if isinstance(c,str) and len(c)>5:
                result.project_tree[p]=c; scaffold_files[p]=c
                if "/" not in p: result.root_files[p]=c
    else:
        result.errors.append(f"Phase4: {r['_error']}")
    # 确保__init__.py
    for pkg in ["app","app/routers","app/schemas","app/services","app/dao",
                "app/db","app/db/models","app/domain"]:
        if f"{pkg}/__init__.py" not in result.project_tree:
            result.project_tree[f"{pkg}/__init__.py"]=""
    result.phases_executed.append("scaffold")
    await _p("phase4_done", f"骨架完成: {len(scaffold_files)}文件", 48)

    # Phase 5: 逐模块
    total_mods = len(plan.modules)
    pct_end = 68 if (plan.needs_frontend and plan.complexity_level not in ("micro","small")) else 82
    for idx, mod in enumerate(plan.modules):
        pct = 50 + int((pct_end-50) * idx / max(total_mods,1))
        await _p(f"phase5_{mod.name}", f"Phase 5/7: 模块{mod.name}({idx+1}/{total_mods})...", pct)
        existing = dict(result.project_tree); existing.update(result.root_files)
        r = await _call_llm(
            _phase5_module_prompt(plan, mod, existing, idx==0), "phased_module", state)
        llm_calls += 1
        if "_error" not in r:
            for p,c in r.get("files",{}).items():
                if isinstance(c,str) and len(c)>5: result.project_tree[p]=c
        else:
            result.errors.append(f"Phase5 {mod.name}: {r['_error']}")
    result.phases_executed.append("modules")
    await _p("phase5_done", f"后端模块完成: {total_mods}模块", pct_end)

    # Phase 6: 前端
    if plan.needs_frontend and plan.complexity_level not in ("micro","small"):
        await _p("phase6a", "Phase 6/7: 前端骨架...", pct_end+3)
        r = await _call_llm(_phase6_fe_scaffold_prompt(plan), "phased_frontend", state)
        llm_calls += 1
        if "_error" not in r:
            for p,c in r.get("files",{}).items():
                if isinstance(c,str) and len(c)>5: result.frontend_tree[p]=c
        await _p("phase6b", "Phase 6/7: 前端业务代码...", pct_end+8)
        r = await _call_llm(_phase6_fe_code_prompt(plan, result.openapi), "phased_frontend", state)
        llm_calls += 1
        if "_error" not in r:
            for p,c in r.get("files",{}).items():
                if isinstance(c,str) and len(c)>5: result.frontend_tree[p]=c
        result.phases_executed.append("frontend")
        await _p("phase6_done", f"前端完成: {len(result.frontend_tree)}文件", pct_end+14)

    # Phase 7: 整合
    await _p("phase7", "Phase 7/7: 整合补全...", 88)
    existing_all = dict(result.project_tree); existing_all.update(result.root_files)
    integrate_files = _phase7_integrate_prompt(plan, existing_all)
    for p,c in integrate_files.items():
        if isinstance(c,str) and len(c)>0:
            if "/" in p and not p.startswith("docker"):
                result.project_tree[p]=c
            else:
                result.root_files[p]=c
                if p == "docker-compose.yml":
                    result.project_tree[p]=c
    result.phases_executed.append("integrate")
    result.total_llm_calls = llm_calls

    await _p("done", f"生成完成: {len(result.project_tree)}后端+{len(result.frontend_tree)}前端+{len(result.test_tree)}测试文件", 100)
    logger.info(f"PhasedGen complete: {len(result.project_tree)}+{len(result.frontend_tree)}+{len(result.test_tree)} files, {llm_calls} LLM calls, errors={len(result.errors)}")
    return result
