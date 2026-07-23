[返回上级文档](../../README.md)

# Tools 模块 — 工具集

Agent 可调用的外部能力集合，涵盖 Web 搜索、浏览器自动化、沙箱代码执行、工作区文件操作。本模块同时包含与工具集紧密耦合的基础设施：Docker 沙箱（`app/sandbox.py`）和事件总线（`app/events.py`）。

---

## 模块职责

| 子系统 | 职责 |
|---|---|
| Web 搜索 | 多模式搜索（stub / Tavily / Playwright / Remote），统一 `ToolPort` 协议 |
| 搜索引擎抽象 | `SearchEngine` Protocol + Bing/DuckDuckGo 引擎，支持 failover 与健康度追踪 |
| 浏览器自动化 | `BrowserTool`：Agent 可操控的浏览器（导航/点击/输入/截图/提取） |
| 声明式导航 | `NavigationSkill`：YAML 定义的浏览器工作流引擎，带补偿机制 |
| 工作区工具 | 文件读写/命令执行/代码运行，路径隔离防穿越 |
| Docker 沙箱 | Sibling Containers 架构执行用户代码，网络分级 + 资源限制 + 自动清理 |
| 事件总线 | `InMemoryEventBus`：内存缓存 + PG 持久化 + Redis Pub/Sub，驱动 WS 推送 |

---

## Web 搜索（`__init__.py` / `playwright_search.py`）

### 四种模式

通过环境变量控制，优先级：`CONCLAVE_WEB_SEARCH_SERVICE_URL` > `CONCLAVE_WEB_SEARCH_MODE`

| 模式 | 环境变量值 | 说明 |
|---|---|---|
| Stub | `stub`（默认） | 返回空结果，离线/测试模式 |
| Tavily | `tavily` | Tavily API，支持租户级 API Key 覆盖 |
| Playwright | `playwright` | 本地无头浏览器爬取 Bing/DuckDuckGo + 正文提取 |
| Remote | 设置 `CONCLAVE_WEB_SEARCH_SERVICE_URL` | HTTP 远程服务解耦模式，推荐生产使用 |

工厂函数 `get_web_search()` 返回实现 `ToolPort` 协议的单例；`get_web_fetch()` 获取 URL 抓取工具（复用同一实例）。

### ToolPort 统一协议

```python
class ToolPort(Protocol):
    async def search(self, query: str, top_k: int = 5, **kwargs) -> list[dict]:
        """返回证据列表，支持 language/time_range/country/session_key 参数"""
    async def fetch_url(self, url: str, max_chars: int = 5000) -> dict:
        """直接抓取 URL 内容，返回 {url, title, content, chunks, source_tier, signals, error}"""
```

### PlaywrightWebSearch（自建搜索）

文件：`playwright_search.py`

零 API 开销的浏览器搜索方案，架构为 Bing 搜索 → Playwright 渲染 Top-K 页面 → 提取正文。

**反检测策略（v3 增强）：**

1. **CDP 注入**：`page.evaluate()` 通过 Chrome DevTools Protocol 在 V8 引擎执行 JS，不经过 DevTools UI，基于 debugger 语句/console 时差的反调试无效
2. **指纹覆盖 v3（30 项）**：WebGL/Canvas 指纹随机化、WebRTC 防泄漏、硬件参数伪装、mediaDevices/Battery API 伪装、chrome.runtime 完整模拟、CDP 特征清除
3. **Session 预热 + Cookie 持久化**：首次启动访问 Bing 首页、接受 cookie、执行预热搜索；Cookie 持久化到磁盘跨重启复用
4. **查询翻译**：中文查询自动翻译为英文（Hunyuan-MT-7B），英文搜索质量更高、延迟更低（4.5s vs 60s）
5. **CAPTCHA 主动检测**：识别 Cloudflare/reCAPTCHA/hCaptcha/极验/腾讯/百度等验证码，5 秒内快速跳过，被拦截域名 5 分钟冷却
6. **拟人化行为**：随机延迟、真实请求头、模拟滚动、逐字输入而非瞬间 fill
7. **异常隔离**：每个页面在独立 BrowserContext 中执行，单页失败不影响其他页面

**并发控制**：使用 `LazySemaphore(3)` 限制并发页面数，`LazyLock()` 保护浏览器初始化（遵循 AGENTS.md §4.1 循环感知原语规范）。

> **Docker 部署注意（AGENTS.md §4.2）**：Playwright 运行时依赖（libglib2.0-0、libnss3、libatk1.0-0、libgbm1、libasound2、libxshmfence1、libgtk-3-0 等）**必须安装在最终运行阶段（work 阶段）**，不能只装在 playwright builder 阶段。Debian Bookworm 使用 `libasound2`（不是 Trixie 的 `libasound2t64`）。

---

## 搜索引擎抽象（`search_engine.py`）

文件：`search_engine.py` + `engines/` 子目录

### 设计原则

- **搜索与提取分离**：`SearchEngine` 只负责 SERP 检索（返回 URL 列表），页面内容提取由调用方或共享 ContentExtractor 负责
- **SearchResult 携带 signals bag**：不预折叠为单一分数，保留引擎原始信号供下游排序
- **引擎健康度追踪**：连续失败 N 次标记为不可用，定时探活恢复
- **MultiEngineSearch**：自动在引擎间 failover 切换

### SearchResult 结构

| 字段 | 类型 | 说明 |
|---|---|---|
| `url` | str | 结果 URL |
| `title` | str | 标题 |
| `snippet` | str | 搜索引擎摘要 |
| `domain` | str | 自动从 URL 解析 |
| `source_tier` | str | 来源等级 S/A/B/C/D |
| `signals` | dict | 信号包（不折叠为单一分数） |
| `rank` | int | SERP 原始排名 |
| `engine` | str | 来源搜索引擎名 |

### 引擎实现

| 引擎 | 文件 | 说明 |
|---|---|---|
| `BingPlaywrightEngine` | `engines/bing_engine.py` | Bing 搜索（Playwright 表单提交） |
| `DuckDuckGoEngine` | `engines/ddg_engine.py` | DuckDuckGo 搜索（备用引擎） |

---

## BrowserTool（浏览器自动化）

文件：`browser_tool.py`

生产级 Agent 浏览器操作工具集，v2 架构升级：

| 维度 | v1 | v2 |
|---|---|---|
| 浏览器管理 | 全局单例 | BrowserPool（按 meeting_id 隔离 BrowserContext） |
| 并发控制 | Semaphore(5) 共享 page | 每 Page 独立 Lock（同页串行，跨页并行） |
| 安全 | 无 | 域名白名单 + scheme 校验 + 私网拒绝 + 重定向校验 |
| 审计 | 无 | 结构化日志（LogBus）+ 脱敏 |
| 内容提取 | 单路径 | 渐进式降级链（DOM → 动态等待 → evaluate） |
| 验证码 | 无 | 区分 403/验证码/超时，分别走降级路径 |

### 资源限制

- `MAX_CONTEXTS = 10`：最多 10 个并行会议
- `MAX_TABS_PER_CONTEXT = 5`：每个会议最多 5 个标签
- `IDLE_TIMEOUT_SECONDS = 600`：空闲 10 分钟回收 Context
- `MAX_NAVIGATION_DEPTH = 15`：最大导航跳转深度
- `MAX_ACTIONS_PER_MINUTE = 30`：操作频率限流
- `EVALUATE_TIMEOUT_SECONDS = 10`：evaluate 超时

### 安全机制

- 始终拒绝 `file://`、`data:`、`javascript:`、`vbscript:` 等危险 scheme
- 拒绝私网/回环/链路本地/保留 IP（`_is_private_ip()`）
- 域名白名单（`ALLOWED_DOMAINS`，空列表 = 允许所有公网域名但拒绝私网）
- 截图大小限制 2MB，evaluate 返回值限制 1MB

---

## NavigationSkill（声明式浏览器导航）

文件：`navigation_skill.py`

YAML 定义的浏览器工作流引擎，而非命令式代码。适用于结构化网站的数据抓取场景。

**核心特性：**

- **声明式 YAML**：定义步骤序列而非编写命令式代码
- **success_when 条件验证器**：8 种条件类型判断每步是否成功
- **四级元素定位回退**：CSS → structural → text → LLM
- **compensating_action**：补偿失败步骤（非通用回滚）
- **partial 状态**：部分步骤成功时返回已获取的数据
- **provenance 标签**：标记数据来源和提取路径
- **fallback-rate 指标**：统计定位回退频率

**用法：**

```python
skill = NavigationSkill.from_yaml(yaml_text)
engine = NavigationSkillEngine()
result = await engine.execute(skill, meeting_id="meeting-123")
# result.status: "success" | "partial" | "failed"
# result.data: 提取的数据
# result.provenance: 数据来源追踪
```

---

## WorkspaceTools（工作区文件操作）

文件：`workspace_tools.py`

供 ReAct 循环中 Agent 自主调用的文件/命令/代码工具，实现"能讨论 → 能动手"的能力升级。

**安全设计：**

- 路径解析通过 `_resolve_path()` 防目录穿越（`Path.resolve()` + `relative_to()` 校验）
- 命令执行复用 `sandbox.run_command()`（白名单检查 + Docker 沙箱隔离）
- 代码运行复用 `sandbox.run_python()`（Docker 沙箱隔离）
- 工具接受 `meeting_id` 参数实现会议间文件隔离（每个会议独立子目录）

**工具集：**

| 工具 | 功能 | 限制 |
|---|---|---|
| 文件读取 | 读取工作区文件内容 | 单次最多 100KB |
| 文件写入 | 写入文件到工作区 | 路径限定在工作区内 |
| 文件列表 | 列出目录内容 | 防目录穿越 |
| 命令执行 | 在沙箱中执行 Shell 命令 | 默认 30s 超时，输出截断 512KB |
| Python 运行 | 在沙箱中执行 Python 代码 | 默认 15s 超时 |

---

## Docker 沙箱（`app/sandbox.py`）

文件：`c:\Users\Huawei\Documents\Conclave\backend\app\sandbox.py`

> 虽然 sandbox.py 位于 `app/` 根目录，但它是 WorkspaceTools/BrowserTool 的底层执行环境，属于工具基础设施的一部分。

### 架构：Docker Sibling Containers

```
宿主机 (Windows / Linux / macOS)
├── Docker daemon
├── Conclave 容器 (Linux)
│   ├── FastAPI 后端
│   ├── docker CLI
│   └── /var/run/docker.sock ← 从宿主挂载
└── 沙箱容器 (按需创建的 sibling)
    └── conclave-workspace 卷 ← 与 Conclave 容器共享
```

- Conclave 容器通过 docker socket 创建 sibling 容器执行用户代码
- **不是 dind**（不需要 `--privileged`），安全性更好
- 本地 Windows 开发时 docker 是 `.cmd` 包装脚本，通过 `create_subprocess_shell` 执行

### 网络分级

| 级别 | 网络 | 用途 |
|---|---|---|
| L1 | `--network none` | 默认，纯计算无网络 |
| L2 | 限网（pypi 白名单） | 允许 `pip install`，走清华镜像，通过 dnsmasq 做域名级过滤 |
| L3 | 全联网 | 明确授权后可访问任意外部 API |

L2 白名单域名：`pypi.org`、`files.pythonhosted.org`、`pypi.python.org`、`pypi.tuna.tsinghua.edu.cn`、`mirrors.tuna.tsinghua.edu.cn`。

### 安全策略

- **资源限制**：`--memory 256m --cpus 1`
- **文件系统**：`--read-only + tmpfs /tmp`
- **权限降级**：`--user 65534:65534 --cap-drop ALL`
- **自动清理**：`--rm`
- **超时控制**：`asyncio.wait_for`
- **多主机调度**：通过 `contextvars.ContextVar`（`_docker_target_env`）传递远程 Docker 主机环境，支持 `docker_host_context()` 上下文管理器

---

## EventBus（事件总线，`app/events.py`）

文件：`c:\Users\Huawei\Documents\Conclave\backend\app\events.py`

> events.py 位于 `app/` 根目录，是工具层（尤其是 BrowserTool 审计、搜索指标）和前端 WebSocket 推送的核心事件管道。

### 架构：内存缓存 + PG 持久化 + Redis Pub/Sub

```
发布事件 → publish()
              ├── save_event() → PostgreSQL（重启不丢）
              ├── history.append() → 内存缓存（新连接回放）
              │     └── history.sort(key=lambda e: e.seq)  # AGENTS.md §4.3
              └── redis.publish() → Redis Pub/Sub（多进程广播）
                                               │
                                    _redis_listener_task 接收
                                    （instance_id 回环防护）
                                               │
                                               ▼
                                         订阅者回调
```

### DomainEvent 结构

| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | str | 事件类型 |
| `meeting_id` | str | 所属会议 |
| `payload` | dict | 事件数据 |
| `schema_version` | str | 载荷 schema 版本，默认 "1.0" |
| `ts` | datetime | UTC 时间戳 |
| `trace_id` | str \| None | 链路追踪 ID |
| `seq` | int | 按 meeting_id 自增序列号（0 开始） |

### 关键实现细节

- **事件顺序**：`history.append()` 后必须按 `seq` 排序（AGENTS.md §4.3），并发 `await save_event()` 的协程恢复顺序不保证与 seq 一致
- **内存安全**：单会议事件历史上限 1000 条，超过自动裁剪最旧事件
- **Redis 桥接循环感知**：遵循 AGENTS.md §4.1，循环已关闭/切换时不使用 Redis 桥接
- **回环防护**：通过 `instance_id`（进程 UUID）过滤自身发出的事件，避免重复处理

---

## 关键文件索引

### tools/ 目录

| 文件 | 职责 |
|---|---|
| `__init__.py` | 搜索工具层：`ToolPort` 协议 + Stub/Tavily/Remote/Playwright 实现 + 工厂函数 |
| `playwright_search.py` | PlaywrightWebSearch：无头浏览器搜索 + 反检测 + SessionPool |
| `search_engine.py` | `SearchEngine` Protocol + `SearchResult` 类型 + 多引擎 failover 框架 |
| `browser_tool.py` | BrowserTool v2：按 meeting_id 隔离的浏览器池 + 安全/审计/降级链 |
| `navigation_skill.py` | NavigationSkill：声明式 YAML 浏览器工作流引擎 |
| `workspace_tools.py` | 工作区文件读写/命令执行/代码运行工具集 |
| `domain_registry.py` | URL 域名标注与来源等级（source_tier）判定 |
| `captcha_guard.py` | CAPTCHA 检测与冷却机制 |
| `rate_limiter.py` | 操作频率限流 |
| `playwright/` | Playwright 辅助脚本（stealth/captcha/chunk/extract/session_pool 等） |
| `engines/` | 搜索引擎实现：`bing_engine.py`（Bing）、`ddg_engine.py`（DuckDuckGo） |

### 紧密关联的基础设施（app/ 根目录）

| 文件 | 职责 |
|---|---|
| `../sandbox.py` | Docker Sibling Containers 沙箱：网络分级（L1/L2/L3）、资源限制、多主机调度 |
| `../events.py` | `InMemoryEventBus` + `DomainEvent`：内存缓存 + PG 持久化 + Redis Pub/Sub |
