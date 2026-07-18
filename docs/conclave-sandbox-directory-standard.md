# Conclave 沙箱目录结构与代码生成规范

**版本**: 1.0
**日期**: 2026-07-18
**状态**: 规范（后续代码生成和文件写入必须遵循）

---

## 一、设计原则

1. **会议隔离**：每次会议的所有产物在独立子目录下，互不干扰
2. **约定优于配置**：固定目录名和文件名，减少 LLM 生成时的歧义
3. **类型感知**：不同交付物类型（数据分析/测试系统/可部署服务）使用不同的目录布局
4. **可部署优先**：生成的代码应可直接运行/部署，无需手动整理
5. **安全边界**：所有代码执行和文件操作限制在会议目录内，禁止访问其他会议目录

---

## 二、工作区根目录结构

```
<workspace_root>/                          # 由 CONCLAVE_WORKSPACE_DIR 指定
├── <meeting_id>/                          # 每个会议一个目录（meeting_id 为 UUID/短ID）
│   ├── (各类型子目录，见下文)
│   └── .conclave/                         # Conclave 元数据目录（系统管理，LLM 不应修改）
│       ├── exec_history/                  # 代码执行历史记录
│       ├── artifacts/                     # 生成产物的元数据
│       └── state.json                     # 会议执行状态
├── _conclave_exec.py                      # [LEGACY] 临时代码文件（将迁移到会议目录内）
└── _shared/                               # 跨会议共享资源（只读，pip 缓存等）
```

**关键约束**：
- `meeting_id` 目录名仅允许 `[a-zA-Z0-9_-]` 字符
- 禁止通过 `..` 访问其他会议目录（路径穿越防护已在 `_resolve_path()` 中实现）
- 沙箱容器内工作目录始终为 `/workspace/<meeting_id>/`（对应宿主机/后端容器的 `<workspace_root>/<meeting_id>/`）

---

## 三、按交付物类型的目录规范

### 3.1 code_analysis / data_science（数据分析类）

适用场景：数据分析报告、可视化、统计计算、机器学习实验。

```
<meeting_id>/
├── main.py                    # 主分析脚本（入口）
├── requirements.txt           # Python 依赖（可选，数据科学镜像已预装 pandas/numpy/matplotlib/sklearn/scipy/seaborn）
├── data/                      # 数据文件目录（用户上传或代码生成）
│   ├── input.csv
│   └── ...
├── output/                    # 输出目录（图表、报告、处理后数据）
│   ├── figures/               # 生成的图表
│   └── results/               # 计算结果
└── README.md                  # 分析说明（可选）
```

**执行方式**：`python main.py`（在 L3/L2/L1 沙箱中运行）
**入口检测**：如果存在 `main.py`，直接执行；否则将代码写入 `main.py` 后执行
**输出约定**：
- 图表保存到 `output/figures/`
- 数据结果保存到 `output/results/`
- stdout 输出作为分析结果文本

### 3.2 tested_system（可测试系统类）

适用场景：算法实现、工具函数、需要单元测试验证的代码模块。

```
<meeting_id>/
├── src/                       # 源代码目录
│   ├── __init__.py
│   └── <module_name>.py       # 主模块
├── tests/                     # 测试目录
│   ├── __init__.py
│   └── test_<module>.py       # pytest 测试文件
├── requirements.txt           # Python 依赖
├── main.py                    # [可选] 独立运行入口
└── README.md                  # 使用说明
```

**执行方式**：`python -m pytest tests/ -v`（在沙箱中运行测试）
**验证逻辑**：
1. 写入 `src/` 和 `tests/` 代码
2. 安装 `requirements.txt` 中的依赖（需要 L2 网络）
3. 运行 pytest，收集测试结果
4. 如有失败，通过 refine_loop 自动修复代码
**入口检测**：`tests/` 目录存在且包含 `test_*.py` 文件时使用此布局

### 3.3 deployable_service（可部署服务类）

适用场景：Web 应用、API 服务、需要长期运行的可访问服务。

```
<meeting_id>/
├── app/                       # 应用代码目录
│   ├── __init__.py
│   ├── main.py                # FastAPI/Flask 入口（必须包含 app 实例）
│   ├── routers/               # 路由模块（可选）
│   │   └── __init__.py
│   ├── models.py              # 数据模型（可选）
│   └── utils.py               # 工具函数（可选）
├── frontend/                  # 前端静态资源（可选，纯后端 API 可省略）
│   ├── index.html             # 主页面
│   ├── css/
│   │   └── style.css
│   └── js/
│       └── app.js
├── tests/                     # 服务测试（可选）
│   └── test_api.py
├── requirements.txt           # Python 依赖（必须包含 fastapi uvicorn[standard] python-multipart）
├── Dockerfile                 # Docker 构建文件（可选，无则使用默认 Python 镜像启动）
├── docker-compose.yml         # Docker Compose 配置（可选，用于多服务架构）
├── .env.example               # 环境变量示例
├── data/                      # 运行时数据目录（容器内创建，挂载持久化）
├── uploads/                   # 上传文件目录
└── README.md                  # 服务文档（必须包含 API 端点说明）
```

**部署方式**：通过 `deploy_service()` 创建 Docker 容器
**健康检查**：必须提供 `/health` 端点（如未实现，Conclave 自动注入）
**端口**：内部端口固定为 `8000`（容器内），由 Conclave 映射到宿主机随机端口（18000-18999）
**启动命令优先级**：
1. 如果存在 `Dockerfile`：`docker build` + `docker run`（使用镜像内 CMD）
2. 如果存在 `docker-compose.yml`：使用 `docker compose up`（未来支持，见第七节）
3. 否则：`pip install -r requirements.txt && uvicorn app.main:app --host 0.0.0.0 --port 8000`

**入口检测**：
- `app/main.py` 存在且包含 FastAPI/Flask app 实例
- 或根目录 `app.py` 存在（向后兼容旧格式）
- 或 `Dockerfile` 存在

#### 3.3.1 Dockerfile 编写规范

```dockerfile
# 基础镜像（Conclave 会自动替换为国内镜像源加速构建）
FROM python:3.12-slim

# 工作目录（固定为 /app，与 Conclave 部署约定一致）
WORKDIR /app

# 先复制依赖文件，利用 Docker 缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制应用代码
COPY app/ ./app/
COPY frontend/ ./frontend/  # 如有前端

# 创建运行时目录
RUN mkdir -p data uploads

# 暴露端口（固定为 8000）
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**注意**：Conclave 在构建时会自动：
- 将 FROM 基础镜像替换为国内镜像源（SWR）
- 如果检测到 `frontend/` 目录但 Dockerfile 中没有 COPY frontend，自动追加
- 创建临时 `.dockerfile.conclave` 用于构建，不修改原始 Dockerfile

#### 3.3.2 单容器 vs 多服务（Docker Compose）

当前版本 `deploy_service()` 支持单容器部署。多服务（docker-compose）场景规划如下：

```
<meeting_id>/
├── docker-compose.yml         # 必须包含，定义多服务架构
├── backend/                   # 后端服务目录
│   ├── Dockerfile
│   ├── app/
│   └── requirements.txt
├── frontend/                  # 前端服务目录
│   ├── Dockerfile
│   ├── nginx.conf
│   └── ...
├── docker/                    # Docker 相关配置
│   └── ...
└── README.md
```

**DinD 问题说明**：
- **一次性沙箱**（run_python/run_command）：**禁止**访问 Docker，不能运行 docker/docker-compose 命令。这是安全设计，防止沙箱逃逸。
- **deploy_service**：在 Conclave **后端容器**内执行 docker CLI，通过 Docker socket（或 socket proxy）连接宿主 Docker daemon，创建 sibling 容器。这不是 DinD（Docker-in-Docker），而是 sibling container 模式，因此：
  - 可以运行 `docker build`、`docker run`、`docker compose up` 等命令
  - 不需要在沙箱容器内安装 Docker CLI
  - 不需要挂载 Docker socket 到沙箱容器
  - 不会因为沙箱的 DinD 防护而影响服务部署

未来如果需要支持 docker-compose 部署：
1. 在后端容器内安装 docker-compose（docker CLI plugin）
2. socket proxy 需要开放 COMPOSE 相关 API 权限（目前 NETWORKS=1 已足够，因为 compose 主要使用 containers/networks/volumes API）
3. deploy_service 检测到 `docker-compose.yml` 时使用 `docker compose up -d` 而非 `docker run`
4. 需要处理多端口映射和服务发现

---

## 四、通用文件命名规范

| 文件/目录 | 命名规则 | 说明 |
|-----------|----------|------|
| Python 入口 | `main.py` 或 `app/main.py` | 统一入口文件名 |
| 依赖清单 | `requirements.txt` | 使用 pip 格式 |
| 测试目录 | `tests/` | pytest 自动发现 |
| 数据目录 | `data/` | 输入数据，只读或追加 |
| 输出目录 | `output/` | 生成产物 |
| 前端目录 | `frontend/` | 静态资源 |
| 文档 | `README.md` | 必须使用 UTF-8 编码 |
| 环境变量示例 | `.env.example` | 不含真实密钥 |
| Docker 构建 | `Dockerfile` | 无后缀 |
| Compose 配置 | `docker-compose.yml` | 多服务时使用 |

### 禁止的文件/目录名

- `__pycache__/`、`.pytest_cache/`、`*.pyc`（Python 缓存）
- `node_modules/`（前端依赖，应通过构建步骤安装）
- `.env`（包含密钥，只允许 `.env.example`）
- `.git/`、`.gitignore`（会议目录不是 git 仓库）
- `conclave_data.json`、`_conclave_*`（系统保留前缀）

---

## 五、文件写入安全规范

### 5.1 路径安全

所有文件写入必须使用 `_resolve_path()` 函数（`workspace_tools.py` 和 `workspace.py` 中均有实现）：
```python
def _resolve_path(user_path: str, workspace_root: Path, meeting_id: str | None = None) -> Path:
    """将用户提供的路径解析为安全的绝对路径，阻止目录穿越"""
    base = workspace_root / meeting_id if meeting_id else workspace_root
    target = (base / user_path).resolve()
    target.relative_to(base.resolve())  # 抛出 ValueError 如果越界
    return target
```

### 5.2 文件大小限制

- 单个代码文件不超过 100KB
- 单个数据文件不超过 50MB（通过配置调整）
- 单次写入总大小不超过 200MB

### 5.3 允许的文件类型

代码文件（文本）：
- `.py`, `.js`, `.ts`, `.html`, `.css`, `.json`, `.yaml`, `.yml`, `.md`, `.txt`, `.csv`, `.toml`, `.cfg`, `.ini`, `.sh`, `.sql`

数据文件（二进制）：
- `.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`, `.pdf`, `.parquet`, `.pkl`, `.npy`, `.xlsx`

禁止的文件类型：
- `.exe`, `.dll`, `.so`, `.bat`, `.cmd`, `.ps1`（可执行文件）
- `.ssh/`, `.aws/`, `.docker/` 下的凭据文件

---

## 六、沙箱执行约定

### 6.1 网络级别自动检测

代码执行前自动检测所需网络级别：

| 检测到的关键词 | 网络级别 | 说明 |
|---------------|---------|------|
| 无网络相关代码 | L1（无网络） | 默认，纯计算 |
| `pip install`、`import requests`/`urllib`/`httpx`/`aiohttp`、`http://`/`https://` | L2 或 L3 | 安装依赖→L2；外部 API→L3 |

L2（限网）当前仅允许以下域名：
- `pypi.org`, `files.pythonhosted.org`, `pypi.python.org`（PyPI 官方）
- `pypi.tuna.tsinghua.edu.cn`, `mirrors.tuna.tsinghua.edu.cn`（清华镜像）

### 6.2 资源限制

| 资源 | 一次性沙箱 | 部署服务容器 |
|------|-----------|-------------|
| 内存 | 256MB（可配置） | 512MB（可配置） |
| CPU | 1 核 | 2 核 |
| 进程数 | 64（pids-limit） | 无限制 |
| 执行超时 | 30-120 秒 | 不限（常驻运行） |
| 文件系统 | 只读根 + tmpfs | 可写 |
| 用户 | nobody (65534) | root（容器内） |
| 网络 | L1/L2/L3 分级 | bridge（全联网） |

### 6.3 执行流程

```
produce 阶段生成代码
    ↓
写入 <meeting_id>/ 目录（遵循目录规范）
    ↓
检测网络级别
    ↓
如需 L3 网络 → 发起授权申请（net_auth）
    ↓ （用户批准或 AUTO_APPROVE=1）
run_python / run_command 执行
    ↓
收集 stdout/stderr/exit_code
    ↓
失败？→ refine_loop 修复代码 → 重新执行（最多 5 轮）
    ↓
成功 → 保存输出，进入下一阶段
```

---

## 七、未来扩展（Roadmap）

### 7.1 Docker Compose 多服务部署

当 `docker-compose.yml` 存在时，`deploy_service` 应：
1. 校验 compose 文件安全性（禁止 privileged、host network、挂载宿主机敏感路径）
2. 使用 `docker compose -p conclave-svc-<meeting_id> up -d` 启动
3. 健康检查所有服务的 /health 端点
4. 端口映射使用 18000-18999 范围
5. 停止时使用 `docker compose down -v` 清理

### 7.2 前端项目支持

当前前端限制为 CDN 模式（`frontend/index.html` 通过 CDN 引入 React/Vue）。未来支持：
- `package.json` + npm build 流程
- `frontend/Dockerfile` 独立构建
- Node.js 沙箱镜像（类似数据科学镜像预装 npm/yarn）
- L2 网络白名单添加 npm 镜像域名

### 7.3 .conclave/ 元数据目录

```
<meeting_id>/.conclave/
├── manifest.json              # 交付物类型、入口文件、端口等元数据
├── exec_history/
│   ├── 001_main.py            # 每次执行的代码快照
│   ├── 001_stdout.txt
│   ├── 001_stderr.txt
│   └── 002_main.py
└── artifacts/
    └── deploy.json            # 部署信息（container_id, port, access_url）
```

---

## 八、迁移说明

当前代码中存在一些旧的文件布局需要逐步迁移：

| 旧布局 | 新布局 | 优先级 |
|--------|--------|--------|
| `app.py` 在会议根目录 | `app/main.py` | 高（deployable_service） |
| `_conclave_exec.py` 在 workspace 根 | `<meeting_id>/_conclave_exec.py` 或 `main.py` | 高（已通过路径修复解决） |
| `test_generated.py` | `tests/test_module.py` | 中 |
| `main_generated.py` | `src/module.py` | 中 |
| frontend 文件仅 3 个白名单文件 | 支持子目录（css/js/assets） | 中 |

---

## 九、给 LLM 的 Prompt 约束

在 produce 阶段的 prompt 中，必须包含以下指令：

```
你必须严格遵循 Conclave 沙箱目录规范：
1. 所有代码文件写入 /workspace/<meeting_id>/ 目录下
2. 根据交付物类型使用正确的目录结构：
   - 数据分析：main.py + data/ + output/
   - 可测试系统：src/ + tests/ + requirements.txt
   - 可部署服务：app/main.py + frontend/ + requirements.txt + Dockerfile
3. Python 入口文件必须是 main.py 或 app/main.py
4. 依赖写入 requirements.txt
5. 禁止使用绝对路径写入文件
6. 禁止访问 /workspace/ 以外的目录
7. 可部署服务必须在 app/main.py 中提供 /health 端点
8. 可部署服务内部监听 0.0.0.0:8000
```
