# 代码审核修复归档

**修复日期**: 2026-07-01  
**修复模型**: DeepSeek 4 Pro  
**验证**: 56 个回归测试全部通过

---

## 修复清单

### P1/S2 — `_extract_json` split 缺长度检查
- **文件**: `backend/app/agents/llm.py:627-639`
- **问题**: `content.split("\n", 1)[1]` 当 content 为单行 ``` 时会 IndexError
- **修复**: 加 `len(parts) >= 2` 检查

### P2/N2 — `_extract_json` rsplit 不处理缺闭合
- **文件**: `backend/app/agents/llm.py:627-639`（同 P1，合并修复）
- **问题**: `rsplit("```", 1)` 找不到闭合时返回原始含围栏内容，json.loads 必然失败
- **修复**: 加 `len(closing) >= 2` 检查

### P3/M3 — Qdrant 内存短路导致重启后检索失效
- **文件**: `backend/app/rag/store.py:254-284`
- **问题**: `if not self._store: return []` 继承自父类，重启后内存为空即使 Qdrant 有数据也返回空列表
- **修复**: 移除短路逻辑，直接走 Qdrant 查询

### P4/N1 — Qdrant except 回退是死路径
- **文件**: `backend/app/rag/store.py:279-284`
- **问题**: except 分支 `return super().search()` 在重启后与直接 `return []` 等价（内存也为空）
- **修复**: 保留回退（同会话内有缓存时仍有效），但加 warning 日志标注缓存条数

### F821 — `nodes.py:628` Path 未导入
- **文件**: `backend/app/orchestrator/nodes.py:9`
- **问题**: `_scan_artifacts(ws_root: Path, ...)` 函数签名使用 `Path` 类型，但模块顶部未导入
- **修复**: 模块顶部加 `from pathlib import Path`，清理 4 处冗余局部导入

---

## 交叉审校记录

原始审核由 Qwen 3.7 进行，报告 10 个问题。DeepSeek 4 Pro 交叉验证后判定：
- **2 个真实** (S2/M3) — 已修复
- **1 个真实但不严重** (L2) — 设计意图，无需修复
- **7 个虚假** (S1/M1/M2/M4/M5/L1/L3) — 行号/方法名/代码片段与实际不符
- **2 个新发现** (N1/N2) — 已修复

原始审核文档 `audit-2026-07-01-v2.md` 已在修复后删除，本文件作为修复回溯依据保留。
