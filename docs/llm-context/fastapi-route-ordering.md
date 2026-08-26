# FastAPI 路由顺序规则

## 核心陷阱：静态路径被动态路由拦截

FastAPI 路由匹配**按定义顺序**执行，不是按特异性匹配。如果动态路由（含路径参数）定义在静态路由之前，静态路径会被当作动态参数匹配。

### 错误模式

```python
# ❌ 错误：动态路由在静态路由之前
@router.get("/{host_id}")      # 匹配所有 GET /xxx
async def get_host(host_id: str):
    ...

@router.get("/overview")       # 永远不会被执行！"overview" 被当作 host_id
async def get_overview():
    ...
```

请求 `GET /overview` 时，FastAPI 匹配到第一个路由 `/`，将 `"overview"` 作为 `host_id` 参数传入，导致 `/overview` 的 handler 永远不会被调用。

### 正确模式

```python
# ✅ 正确：静态路由在动态路由之前
@router.get("/overview")               # 先匹配静态路径
@router.get("/commands-reference")     # 再匹配其他静态路径
@router.get("/{host_id}")              # 最后匹配动态路径
async def get_host(host_id: str):
    ...
```

## 规则

1. **静态路径永远定义在动态路径之前**。这包括：
   - `@router.get("/fixed-path")` 在 `@router.get("/{param}")` 之前
   - `@router.post("/action")` 在 `@router.put("/{id}")` 等动态路由之前
   - 子路径同理：`/hosts/{id}/overview` 与 `/hosts/overview` 也有此问题

2. **路径参数尽量使用类型约束**，减少误匹配：
   ```python
   # 更好：约束 host_id 为 UUID 格式，不会匹配 "overview"
   @router.get("/{host_id}")
   async def get_host(host_id: UUID = Path(...)):
       ...
   ```

3. **路由文件新增路由时**，始终检查文件中已有路由的顺序，确保新添加的静态路径不在动态路径之后。

## 如何自查

在每个路由文件中搜索 `/{` 找到动态路由，确认其后没有未被它覆盖的静态路径：

```bash
# 检查所有路由文件中的动态路由定义
grep -n '@router\.\(get\|post\|put\|delete\|patch\)("/{' backend/app/routers/*.py backend/app/plugins/**/router.py
```

如果发现动态路由之后有静态路径定义，调整顺序。

## 受影响的文件

本项目中以下文件有动态路由，修改时需特别注意：

- `backend/app/routers/meetings.py` — `/{meeting_id}`
- `backend/app/routers/workspace.py` — `/files/{file_path:path}`（path 类型参数匹配所有子路径）
- 任何包含 `{tenant_id}`、`{user_id}`、`{host_id}` 等路径参数的路由文件

## 同类框架注意事项

- **Express.js / Koa**：同样按注册顺序匹配，同样存在此问题
- **Django / Flask**：Django URL patterns 按顺序匹配；Flask 有类似行为
- **Spring Boot**：按特异性匹配，不存在此问题

这不是 FastAPI 独有的 bug，而是大多数 Python/Node Web 框架的共性行为。
