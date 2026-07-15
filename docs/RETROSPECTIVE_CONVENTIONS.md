# Conclave 修复报告归档规范

> **版本**: 1.1
> **生效日期**: 2026-07-16
> **适用范围**: 所有代码修复、Bug修复、架构调整、UI/UX优化后的总结报告

---

## 1. 为什么需要修复报告

每次系统性修复（无论是Bug修复、架构重构、功能迭代还是UI/UX优化），都会产生大量代码变更和决策。修复报告的作用：

1. **经验沉淀**：记录Bug根因，避免重犯同类错误
2. **增量追溯**：后续AI/开发者可以基于历史报告快速理解上下文，生成递增的新报告
3. **审计合规**：每次重大变更都有完整记录
4. **知识传递**：新成员可以通过报告快速了解系统演进历史
5. **AI优化基础**：AI可以基于历史报告和新报告进行对比分析，持续优化修复策略

---

## 2. 报告存放位置

### 2.1 主存放目录

所有修复报告统一存放在项目仓库的：

```
docs/retrospectives/
├── YYYY-MM-DD-{slug}.html    # HTML格式的完整报告（主要格式，必须生成）
└── YYYY-MM-DD-{slug}.md      # Markdown格式（可选，简要版本）
```

- **目录**：`docs/retrospectives/`（如不存在需创建）
- **命名规则**：`YYYY-MM-DD-{简短描述}.html`，使用小写字母和连字符，例如：
  - `2026-07-16-docker-startup-and-ux-fixes.html`
  - `2026-07-16-navigation-ux-audit.html`
  - `2026-07-14-architecture-refactor.html`
- **格式**：**必须**使用 HTML 报告（通过 `html-report` skill 生成），视觉效果好、可直接在浏览器打开、支持图表和交互

### 2.2 项目管理工具关联

在 Redmine（或其他项目管理工具）中：

- **专门位置**：在项目的"文档"或"知识库"板块建立"修复回顾"分类
- **关联方式**：
  - 每个迭代/Sprint结束后，在对应Redmine任务中附加报告链接
  - 报告文件名应包含日期和关键词，便于搜索
  - Redmine任务描述中引用报告相对路径：`Refs: docs/retrospectives/2026-07-16-xxx.html`

### 2.3 历史报告处理

历史报告（之前存放在 `docs/audits/` 下）保持原位不动，新报告统一放 `docs/retrospectives/`。

---

## 3. 何时生成报告（强制要求）

### 3.1 必须生成报告的场景

以下情况**每次都必须**生成修复报告，**没有例外**：

| 场景 | 报告类型 | 示例 |
|------|---------|------|
| 修复阻断性Bug（P0/P1） | 完整HTML报告 | Docker启动失败、服务崩溃、数据丢失 |
| 一轮系统性修复（≥3个Bug） | 完整HTML报告 | 深夜Bug修复Session、UI/UX全面审校 |
| 架构级重构 | 完整HTML报告 | DB层统一、AgentRuntime重构 |
| 安全修复 | 完整HTML报告 | Docker socket加固、认证漏洞修复 |
| UI/UX全面审校和优化 | 完整HTML报告 | 导航流程重构、交互逻辑统一 |
| 依赖升级或版本迁移 | 完整HTML报告 | React 18升级、PostgreSQL大版本升级 |

### 3.2 建议生成报告的场景

| 场景 | 报告类型 | 示例 |
|------|---------|------|
| 单个中等级别Bug修复（P2） | 简短HTML报告或在commit message中详细描述 | 表单验证修复、样式错位修复 |
| 功能增量迭代 | 完整HTML报告 | 新增时区配置、用户中心功能 |

### 3.3 可免报告的场景（极少）

- 单个极小Bug修复（<3个文件，无架构影响）：拼写错误、颜色微调、日志补充
- 代码注释补充、文档微调

---

## 4. Commit区间描述规范（重点）

### 4.1 区间定义

每份报告**必须在最显眼的位置**（报告头部meta信息区）明确标注Commit区间：

```html
<div class="report-meta">
  <span>📅 2026年7月16日</span>
  <span>🔖 Commit区间: <code>3fb8910</code> → <code>ec743df</code></span>
  <span>🔧 3个P0 / 8个P1 / 10个P2修复</span>
  <span>📝 完整追溯文档</span>
</div>
```

### 4.2 起止Commit确定方法

- **起始Commit**：本轮修复**开始前**的最后一个commit。在开始修复前执行 `git rev-parse --short HEAD` 获取并记录。
- **结束Commit**：本轮修复**完成后**，报告生成并提交后的那个commit。
- **获取区间commit列表**：
  ```bash
  git log --oneline <start-hash>..HEAD
  ```

### 4.3 区间内Commit列表

报告中必须列出本次修复涉及的所有commit：

```markdown
## Commit区间详情

- **起始Commit**: `3fb8910` - fix: TS errors, Docker TZ, meeting creation options
- **结束Commit**: `ec743df` - fix: resolve Docker startup crash, fix navigation issues, add user center, improve UX

### 本次修复的Commit列表

| Hash | 描述 |
|------|------|
| `ccf1ba6` | feat: timezone config, meeting mode selector, Docker TZ support |
| `189b664` | fix: P0/P1 bugfixes, memory protection, WS optimization, instant mode rename |
| `ec743df` | fix: resolve Docker startup crash, fix navigation issues, add user center, improve UX |
```

### 4.4 递增报告生成

后续生成新报告时：

1. 前一份报告的**结束Commit** = 后一份报告的**起始Commit**
2. 新报告开头应简要引用上一份报告：`上一轮修复: 3fb8910 → ec743df (docs/retrospectives/2026-07-16-xxx.html)`
3. 形成连续的修复链条，AI可以读取所有历史报告进行增量分析

---

## 5. 报告必须包含的内容

每份修复报告**必须**包含以下章节：

### 5.1 报告头部（Meta信息）

- 报告标题
- 日期
- **Commit区间**（必须，醒目位置）
- 问题统计（P0/P1/P2/P3数量）
- 作者/执行者

### 5.2 问题概述

- 发现了多少个问题
- 问题的严重程度分布（P0/P1/P2/P3数量）
- 影响范围（哪些模块/功能受影响）
- 问题发现的背景（用户反馈、AI审计、测试发现等）

### 5.3 修复详情

每个Bug/问题必须包含：
- **优先级**：P0/P1/P2/P3
- **现象**：用户看到什么/发生了什么
- **根因**：为什么会发生（技术层面，不是表面原因）
- **修复方式**：怎么修的，关键代码变更
- **影响文件**：哪些文件被修改
- **验证方式**：怎么确认修好了

### 5.4 根因归类

将Bug按错误模式归类（参考第8节的典型错误模式），帮助识别系统性问题。

### 5.5 经验沉淀与改进建议

从这次修复中学到了什么？如何预防同类问题？列出具体的改进建议：
- 需要增加的测试
- 需要添加的CI门禁
- 需要完善的代码规范
- 架构层面需要改进的地方

### 5.6 遗留问题

未在本轮修复的问题，记录下来供后续迭代：
- 问题描述
- 为什么本轮不修
- 建议后续何时处理

### 5.7 验证结果

- TypeScript/Python编译检查结果
- 单元测试/构建结果
- Docker构建和运行状态验证
- 手动验证的关键流程

---

## 6. Commit消息规范

### 6.1 引用报告

每次修复提交时，commit message **必须**附带报告引用：

```
<type>: <description>

<详细描述>

Refs: docs/retrospectives/2026-07-16-navigation-ux-audit.html
```

### 6.2 Commit粒度建议

- 一批相关修复可以放在一个commit中
- 每轮修复的最后一个commit（合并性commit）必须引用报告路径
- 如果修复过程中产生多个commit，每个commit message应清晰描述该commit的内容

### 6.3 Type类型

使用以下type前缀：
- `fix:` - Bug修复
- `feat:` - 新功能
- `refactor:` - 重构（不改变功能）
- `docs:` - 文档更新
- `test:` - 测试相关
- `chore:` - 构建/工具链相关

---

## 7. AI辅助修复时的工作流

当AI（如Trae）执行修复任务时，**必须**遵循以下流程：

### 7.1 开始修复前（强制步骤）

1. **确定起始Commit**：
   ```bash
   git rev-parse --short HEAD
   ```
   记录下来，这是本轮修复的起始点。

2. **阅读历史报告**：
   - 阅读 `docs/retrospectives/` 下最近的3-5份报告
   - 了解近期修复历史、典型错误模式、已知遗留问题
   - 理解之前的决策背景，避免重复踩坑

3. **阅读项目规范**：
   - 阅读本规范文档
   - 阅读 `docs/design/` 下的设计文档
   - 阅读代码风格配置（.eslintrc, pyproject.toml等）

4. **制定修复计划**：
   - 列出待修复的问题清单（按优先级排序）
   - 预估影响范围
   - 确定验证方式

### 7.2 修复过程中

1. **边修边记录**：不要靠记忆，每修复一个问题就记录下来：
   - 现象
   - 根因分析
   - 修复方式
   - 修改的文件

2. **分批验证**：
   - 每完成一批相关修复，运行编译检查
   - 前端：`cd frontend && npx tsc --noEmit`
   - 后端：`python -m py_compile <file>` 检查语法
   - 避免到最后才发现编译错误

3. **及时提交**：
   - 相关的修复放在一个commit中
   - commit message清晰描述
   - 不需要等所有修复完成才提交

### 7.3 修复完成后（强制步骤）

1. **完整验证**：
   - TypeScript类型检查通过
   - Python语法检查通过
   - Docker镜像构建成功
   - Docker容器启动正常
   - 关键功能流程手动验证

2. **确定结束Commit**：
   - 所有修复代码已commit
   - 执行 `git rev-parse --short HEAD` 获取结束commit hash

3. **生成修复报告**：
   - 使用 `html-report` skill 生成HTML格式报告
   - 报告中**必须**明确标注Commit区间（起始 → 结束）
   - 按照第5节的要求填写所有章节
   - 参考最新的历史报告保持格式一致

4. **保存报告**：
   - 将报告保存到 `docs/retrospectives/YYYY-MM-DD-{slug}.html`
   - 确保报告中所有资源路径（CSS、JS、字体）使用相对路径

5. **最终提交**：
   - 将报告文件加入git
   - 提交，commit message引用报告路径
   - 这个commit就是报告中记录的"结束Commit"

### 7.4 基于历史报告优化（AI增量工作流）

AI在后续修复任务中，应：

1. **读取所有相关历史报告**：按Commit区间顺序阅读
2. **对比分析**：
   - 新问题是否是已知错误模式的重现？
   - 之前的修复是否引入了回归？
   - 之前的经验沉淀是否已经落实？
3. **生成递增报告**：
   - 新报告的起始Commit = 上一份报告的结束Commit
   - 在报告开头引用上一份报告
   - 对比历史数据（问题数量、类型分布等）
4. **更新错误模式**：发现新的典型错误模式时，更新本规范第8节

---

## 8. 典型错误模式参考（持续更新）

以下是历史修复中归纳的典型错误模式，新报告中如发现新模式应追加到本节：

| 模式 | 描述 | 预防措施 |
|------|------|---------|
| API风格混用 | SQLite语法套用到PostgreSQL（conn.execute vs cursor） | DB驱动迁移建立检查清单 |
| 字符串校验代替语义校验 | startswith("{")判断代码有效性 | 用AST解析、schema校验 |
| 重命名后遗留不一致 | 部分引用未更新、存量数据未兼容 | 全局搜索+normalize兼容层 |
| 事件时序错误 | 先通知后决策导致UI闪烁 | "先决策后通知"原则 |
| API契约不一致 | 同端点不同分支返回不同结构 | TypeScript/Pydantic双重约束 |
| 异常路径无收敛 | 异常后状态僵死、无事件通知 | try/except/finally确保状态收敛 |
| BOM污染 | Windows编辑器添加BOM导致解析失败 | .editorconfig + CI BOM检测 |
| 修复引入回归 | 修改代码后不运行编译检查 | CI加py_compile/tsc门禁 |
| 导航路径断裂 | 操作后无明确出口/入口（如会议运行中无法返回） | 每次状态都有明确的返回路径 |
| 重复入口不一致 | 同一功能多个入口，交互不同（如两套会议列表） | 统一交互模式，或明确差异化定位 |
| 删除模式粘滞 | 危险操作（永久删除）的状态保持导致误删 | 危险操作每次确认都重置为安全默认 |
| 状态切换不重置 | 切换会议/页面时局部状态残留（如Tab停留在工作区） | ID变化时重置相关state |
| 文件上传无删除 | 选择文件后无法撤销/重选 | 使用标准Upload组件，支持onRemove |

---

## 9. 报告模板

生成新报告时，可参考 `docs/retrospectives/` 下最新的报告作为模板，保持格式一致。

快速骨架：

```html
<!-- Generated by Trae Work -->
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>修复报告 - YYYY-MM-DD</title>
  <style>
    /* 复用历史报告的CSS变量和样式 */
  </style>
</head>
<body>
<div class="container">
  <header class="report-header">
    <h1>修复报告标题</h1>
    <p class="subtitle">一句话概述本轮修复的核心内容</p>
    <div class="report-meta">
      <span>📅 YYYY年MM月DD日</span>
      <span>🔖 Commit区间: <code>start-hash</code> → <code>end-hash</code></span>
      <span>🔧 N个P0 / N个P1 / N个P2修复</span>
      <span>📝 完整追溯文档</span>
    </div>
    <div class="report-chain">
      上一轮修复: <a href="./YYYY-MM-DD-previous.html"><code>prev-start</code> → <code>prev-end</code></a>
    </div>
  </header>

  <!-- 统计卡片 -->
  <section class="stats-grid">
    <!-- P0/P1/P2/P3 统计 -->
  </section>

  <!-- 1. 问题概述 -->
  <section>
    <h2>1. 问题概述</h2>
    ...
  </section>

  <!-- 2. Commit区间详情 -->
  <section>
    <h2>2. Commit区间详情</h2>
    ...
  </section>

  <!-- 3. 修复详情 -->
  <section>
    <h2>3. 修复详情</h2>
    <!-- 每个问题一个子章节 -->
    ...
  </section>

  <!-- 4. 根因归类 -->
  <section>
    <h2>4. 根因归类</h2>
    ...
  </section>

  <!-- 5. 经验沉淀 -->
  <section>
    <h2>5. 经验沉淀与改进建议</h2>
    ...
  </section>

  <!-- 6. 遗留问题 -->
  <section>
    <h2>6. 遗留问题</h2>
    ...
  </section>

  <!-- 7. 验证结果 -->
  <section>
    <h2>7. 验证结果</h2>
    ...
  </section>
</div>
</body>
</html>
```

---

## 10. 规范版本历史

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| 1.0 | 2026-07-16 | 初始版本，定义了报告位置、基本格式、AI工作流 |
| 1.1 | 2026-07-16 | 强化Commit区间描述规范；增加强制生成报告要求；补充AI增量工作流；增加Redmine关联指引；新增UI/UX相关错误模式 |

---

*本规范自 2026-07-16 起生效，后续所有修复工作均应严格遵循。*
