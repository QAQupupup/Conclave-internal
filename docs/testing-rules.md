# 测试开发守则（Testing Development Rules）

> 本文是 Conclave 项目测试开发的**强制守则**，从 `AGENTS.md` §5.7 迁出独立成文。
> 违反任何一条等同于违反工程规范，CI 有权拒绝合并。
>
> 配套文档：`AGENTS.md`（实战纪律入口）、`docs/sql-development-rules.md`（SQL 开发守则，五级标签同源）。

---

## 0. 标签体系

同 `docs/sql-development-rules.md` §0，五级标签：`【绝对禁止】`/`【红线】`/`【警告】`/`【倾向】`/`【建议】`。

- 【绝对禁止】：违反即 Bug 或测试失效，Code Review 直接拦截。
- 【红线】：默认禁止，命中必须整改。
- 【倾向】：默认优先，有更优理由可替换。

> 历史教训：`verify_password` 段数检查 bug（4 段 vs 5 段）导致所有登录 401，该函数零测试覆盖。
> `test_role_matching.py` 测试逻辑副本而非真实函数。这些不是个例，是系统性测试失效。
> 本守则的每一条都是对真实事故的防御。

---

## 1. 测试必须验证真实代码【绝对禁止】

- **禁止测试逻辑副本**。测试必须 `import` 并调用真实的被测函数，不允许在测试文件中重新实现一份"保持一致"的逻辑。如果被测函数变更，副本不会自动更新，测试通过但真实代码可能有 bug。
  - 错误：`def _match_role(role_str): ...  # 从 nodes.py 提取的匹配逻辑`
  - 正确：`from app.orchestrator.nodes import _match_role`
- **禁止 mock 被测函数本身**。mock 只能用于被测函数的依赖（数据库、外部 API、LLM）。如果被测函数被 mock 了，测试验证的是 mock 行为而非真实代码。
- **测试必须 import 真实模块路径**，不能通过 `sys.path` hack 或动态加载绕过正常 import 链。

## 2. 测试必须有有意义断言【绝对禁止】

- **每个测试函数至少一个断言**。无断言的测试函数（仅调用函数不验证结果）不算测试，必须删除或补全断言。
- **禁止 `assert True` / `pass` / 空函数体**作为测试。测试通过必须有可验证的原因。
- **禁止 `.not.toThrow()` 作为唯一断言**（前端）。必须跟具体的 DOM/状态/返回值断言。"没崩溃"不等于"功能正确"。
- **断言必须验证具体值**，不能只验证类型或存在性。`assert result is not None` 太弱，应改为 `assert result.status == "active"`。
- **异常测试必须用 `pytest.raises` / `expect().toThrow()`**，禁止 `try/except: pass` 吞掉异常后继续执行。吞掉异常意味着你不知道函数是否抛了预期的异常。

## 3. 配对函数必须有往返测试【红线】

以下配对函数类型，提交时必须附带"正向验证通过 + 反向验证拒绝"的往返测试：

| 配对类型 | 示例 | 必须覆盖 |
|---------|------|---------|
| hash/verify | `hash_password` / `verify_password` | 正确密码通过 + 错误密码拒绝 |
| encode/decode | `_b64url_encode` / `_b64url_decode` | 往返一致 + 格式校验 |
| create/verify | `create_jwt` / `verify_jwt` | 有效 token 通过 + 篡改 token 拒绝 + 过期 token 拒绝 |
| encrypt/decrypt | 任何加解密对 | 往返一致 + 密钥错误拒绝 |
| serialize/deserialize | `model_dump` / `model_validate` | 往返一致 + 格式错误拒绝 |

**没有往返测试的配对函数，禁止合并。** 这是 `verify_password` 401 bug 的直接预防措施。

## 4. 关键安全函数必须有专项测试【红线】

以下函数是认证/安全的心脏，必须有独立的测试文件覆盖：

- `app/auth.py`：`hash_password` / `verify_password` / `create_jwt` / `verify_jwt` / `authenticate_user`
- `app/plugins/builtin/auth/middleware.py`：Cookie 解析、token 提取
- `app/plugins/builtin/auth/csrf.py`：CSRF token 生成与验证
- `app/tenants/service.py`：租户隔离（跨租户数据不可见）

新增安全相关函数时，同步新增对应测试文件。无测试的安全函数禁止合并。

## 5. 测试禁止依赖外部状态【红线】

- 测试禁止依赖外网（Bing/OpenAI 等）。必须 mock 或走 stub。
- 测试禁止依赖执行顺序。每个 test 必须独立可运行（`pytest -p no:randomly` 随机顺序也能过）。
- 测试用例中的数据必须自包含，不要依赖其他测试留下的数据。
- Flaky 测试（偶发失败）必须修，不能简单 `@pytest.mark.skip` 绕过。
- **`@pytest.mark.skip` / `skipif` 是技术债务，不是解决方案**。每个 skip 必须在注释中说明：(1) 为什么跳过 (2) 什么条件下恢复运行 (3) 恢复的责任人。模块级 skip（整个文件跳过）必须在 `docs/pitfalls.md` 或 issue 中有对应记录。

## 6. 测试必须能检测代码回归【红线】

- **测试必须在被测代码出 bug 时失败**。如果一个测试无论代码是否正确都能通过，它不是测试，是噪音。验证方法：故意改坏被测代码（如把 `==` 改成 `!=`），确认测试失败。
- **Bug 修复必须先加失败用例**。先写一个能复现 bug 的测试（此时应失败），再修复代码（此时应通过）。禁止"先修后测"。
- **禁止通过削弱断言来让测试通过**。如果测试失败，应该修代码或修测试断言值（需 grep 确认真实返回值），不能把 `assert x == 5` 改成 `assert x is not None` 来强行通过。

## 7. 测试代码质量等于生产代码质量【倾向】

- 测试文件必须通过 `ruff check` 和 `ruff format`。
- 测试函数命名必须与断言一致（`test_xxx_has_strength_weak` 不能断言 `"none"`）。
- 测试必须有 docstring 说明验证的场景（一句话即可）。
- 测试中禁止硬编码 magic number 而不说明来源（如 `assert len(result) == 7  # 7 个角色`）。

## 8. 测试执行时机【倾向】

| 时机 | 必须执行的操作 | 验证标准 |
|------|--------------|---------|
| 新增/修改后端函数 | Docker 容器内跑相关测试文件 | 0 failed |
| 新增/修改前端组件 | `npx vitest run` 相关测试文件 | 0 failed |
| 修改认证/安全代码 | 跑 `test_password_hash.py` + 手动 curl 登录验证 | 登录返回 200 |
| 修改 ORM 模型 | 跑全量后端测试（模型变更影响面大） | 0 failed |
| `git commit` 前 | pre-commit hook（ruff/mypy/tsc/eslint） | 0 errors |
| `git push` 前 | pre-push hook（Docker CI 一致性） | 0 failed |
| 后端代码变更后部署 | `docker compose up -d --build backend`（必须重建镜像） | 容器 healthy |

## 9. 禁止"快乐路径唯一测试"【绝对禁止 + 红线】

> 大模型和 Agent 天然擅长写正向测试——给定正常输入，断言正常输出。
> 但正向测试通过 ≠ 功能正确。项目的系统性 bug（阶段跳过、角色丢失、并发竞争、证据缺失）
> 全部发生在正向测试覆盖的"正常路径"之外。
> **只写快乐路径的测试等同于没有测试。**

**强制维度覆盖**：每个新增/修改的函数或模块，除正向测试外，必须至少覆盖以下维度中的 **2 项**（安全/认证类函数必须覆盖"异常 + 越权"）：

| 维度 | 含义 | 典型场景 |
|------|------|---------|
| 边界值 | 输入在极限/临界点 | 空列表、单元素、最大长度、off-by-one、零/负数 |
| 异常路径 | 被测代码应抛错或降级 | LLM 返回 `success=False`、网络超时、格式错误、缺字段 |
| 权限/越权 | 跨用户/跨租户数据隔离 | 用户 A 访问用户 B 的会议、未认证请求、过期 token |
| 并发竞争 | 多线程/协程同时访问 | `asyncio.gather` 并发写 `shared_state`、`compute` 单例竞态 |
| 极限条件 | 超大输入或高负载 | 100+ claims、50+ conflicts、10K 字符 topic、空 `team_config` |
| 回退/降级 | 主流程失败后的兜底路径 | LLM 不可用走 StubLLM、RAG 检索失败走空证据、Cython `.so` 缺失走 `.py` |

**判定标准**（Code Review 时逐项检查）：

1. **每个测试文件至少 1 个非正向测试**。纯 happy-path 测试文件禁止合并。
2. **Stub/Mock 必须有失败分支**。StubCompute 不能只返回 `success=True`，必须覆盖 `success=False` 和格式异常。
3. **状态机/路由测试必须验证非法跳转被拒绝**。不能只测"正确跳转"，必须测"非法跳转被拦截"（如 INTRA_TEAM 不能直接到 EVIDENCE_CHECK）。
4. **并发模块必须有并发测试**。使用 `asyncio.gather` 或 `ThreadPoolExecutor` 模拟并发，断言结果一致性或竞态安全。
5. **有兜底逻辑的函数必须测兜底分支**。`try/except`、`if not x: fallback`、`or default` 等兜底路径必须有对应测试。

**反模式（禁止）**：
- 只测正常输入 + 正常输出，不测异常输入
- Stub 只返回成功，不返回失败
- 只测"能跳到下一阶段"，不测"不能跳过阶段"
- 并发模块只有串行测试
- `assert result is not None` 作为唯一断言（§2 已禁止，这里重申）

**正面模式（鼓励）**：
- 参数化测试覆盖边界值：`@pytest.mark.parametrize("input,expected", [...])`
- Stub 支持 `mode` 参数切换成功/失败/超时
- 测试非法操作被拒绝：`with pytest.raises(...)` 或断言返回错误码
- 并发测试：`await asyncio.gather(*[worker() for _ in range(N)])` + 断言最终状态一致

---

> 新增测试踩坑，追加到 `docs/pitfalls.md` 测试类别（P11-P14, P27）；新增测试规则，追加到本文并同步更新 `AGENTS.md` 索引。