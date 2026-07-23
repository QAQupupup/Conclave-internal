## 变更说明

<!-- 简要描述这个 PR 做了什么 -->

## 变更类型

- [ ] Bug 修复
- [ ] 新功能
- [ ] 重构（不改变功能）
- [ ] 文档更新
- [ ] 性能优化
- [ ] CI/CD 或工程配置

## 变更范围

<!-- 涉及哪些模块？例如：orchestrator/agents/frontend/docker -->

-

## 验证方式

<!-- 你如何验证这些改动是正确的？ -->

- [ ] `docker compose -f docker-compose.test.yml run --rm backend-test sh -c "ruff check app conclave_core tests"` 无错误
- [ ] `docker compose -f docker-compose.test.yml up --build --exit-code-from backend-test` 测试通过
- [ ] 手动冒烟测试通过
- [ ] 新增了对应测试用例

## 截图/日志

<!-- 如有 UI 变更或关键日志，请附上截图 -->

## 关联 Issue

<!-- Closes #issue_number -->

## 注意事项

<!-- 是否有 Breaking Change？是否需要更新文档或配置？ -->
