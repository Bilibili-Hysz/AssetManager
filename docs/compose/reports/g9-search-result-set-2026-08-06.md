# G9：SearchResultSet 详细结果契约与 LAN opt-in 状态投影

> 日期：2026-08-06
> 工作区：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak`
> 分支：`master`
> 本报告是主线继续开发记录，不是发布完成声明。

## 1. 本阶段边界

本阶段承接 G5/G6/G7/G8 的审查结论，只处理搜索结果状态的最小演进：

- 保留既有三个 `SearchService.search_by_*()` 的 `list[SearchResult]` 返回合同；
- 增加可选的详细结果模型，不强迫 desktop/旧调用方立即迁移；
- 将 LAN `/api/search` 迁移到详细 API，但默认 JSON 继续只有 `results` 与 `count`；
- 通过 `include_status=1`（也接受 `true`/`yes`）暴露详细状态；
- 不触碰 `webui/**`、`tests/e2e/**`、`tmp/**`；
- 不改变 raw connection 兼容阶段的 `allow_unmanaged` 默认值。

## 2. 实现内容

### 2.1 `SearchResultSet` 最小内部 API

位置：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\search_service.py
```

新增不可变模型：

```python
SearchStatus
SearchError
SearchSourceStatus
SearchResultSet
```

状态集合：

```text
complete
empty
invalid_input
unavailable
error
partial
degraded
path_rejected
```

`SearchResultSet` 记录：

- 不可变的 `tuple[SearchResult, ...]`；
- 顶层状态；
- 每个 source 的状态、结果数、丢弃数、错误数；
- 稳定错误码、source、recoverable 标志；
- `dropped_count`；
- `fallback_used`；
- `count`、`is_complete`、`as_list()` 兼容投影。

`SearchResultSet.merge()` 用于主 source/fallback 聚合：

- 任一 source 失败而存在 fallback 聚合时，结果标记为 `degraded`，不会伪装成 `complete`；
- 没有结果且只发生路径拒绝时标记 `path_rejected`；
- 同一相对路径去重，优先保留主 source 的记录；
- 诊断中不包含原始异常文本、绝对路径、query 或文件名列表。

### 2.2 旧 API 兼容

以下方法仍返回 `list[SearchResult]`：

```python
SearchService.search_by_tags(...)
SearchService.search_by_name(...)
SearchService.search_by_name_indexed(...)
```

对应的详细入口为：

```python
SearchService.search_by_tags_detailed(...)
SearchService.search_by_name_detailed(...)
SearchService.search_by_name_indexed_detailed(...)
```

旧入口只对 `SearchResultSet` 调用 `as_list()`，因此已有 desktop、测试、插件宿主调用方不需要在本阶段改写。

### 2.3 异常与 partial 语义

已明确：

- `sqlite3.ProgrammingError`（典型 closed connection）不被压缩为空结果；
- `sqlite3.OperationalError`（典型 schema/migration failure）不被压缩为空结果；
- managed foreign-root / ownership `ValueError` 继续从 connection validation 传播；
- 已进入 `session_operation` 的 closed `LibrarySession` 继续在业务执行前拒绝；
- 单 tag source 失败、scanner 单行解析失败、indexed 单行路径 containment 失败可形成 `partial`/`path_rejected`；
- provider 无法提供连接仍保留 `unavailable` 详细状态，旧 list API 仍返回空列表；
- 观察性 recorder 失败不改变搜索结果或 fallback。

路径处理统一复用 `_contained_relative_path()`：

- 外部绝对路径；
- `..` 路径；
- 解析后的 symlink escape；

均被拒绝并计入 `dropped_count`，不能进入结果投影。

### 2.4 LAN `/api/search`

位置：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\metadata.py
```

路由现在使用 detailed API：

```text
scanner primary
→ indexed fallback
→ SearchResultSet.merge(..., fallback_used=True)
```

默认响应仍保持：

```json
{
  "results": [],
  "count": 0
}
```

当 `include_status=1` 时，额外返回：

```json
{
  "status": "degraded",
  "sources": [
    {
      "source": "scanner",
      "status": "unavailable",
      "result_count": 0,
      "dropped_count": 0,
      "error_count": 1
    }
  ],
  "errors": [
    {
      "code": "search_source_failed",
      "source": "indexed",
      "recoverable": true
    }
  ],
  "dropped_count": 0,
  "fallback_used": true
}
```

旧 LAN fixture 中没有 `assets` 表时，indexed fallback 的 `OperationalError` 在 transport fallback 边界被记录为 source failure；默认响应保持兼容，详细响应不会把它标记成正常 empty。

LAN route telemetry 保留既有字段：

```text
outcome
status
result_count
```

成功的 200 请求额外带 `search_status`，用于区分 `empty`、`degraded` 等结果状态；403/500 的既有精确错误事件字段不增加敏感信息。

## 3. 回归证据

### 3.1 SearchService 与 LAN 定向回归

```text
python -m pytest -q --tb=short tests/integration/test_search_service.py tests/integration/test_search_result_set_contract.py tests/integration/test_url_projection_contract.py tests/lan/test_lan_api.py
```

结果：

```text
262 passed, 1 skipped
```

skip 仍是 Windows 当前进程没有 symlink/directory-symlink 权限，并非功能失败。

### 3.2 LAN opt-in 状态投影

```text
python -m pytest -q --tb=short tests/lan/test_search_status_route.py
```

结果：

```text
2 passed
```

### 3.3 静态门禁

```text
ruff check AssetsManager/lan/routes/metadata.py
ruff check AssetsManager/application/search_service.py tests/integration/test_search_result_set_contract.py
pyright AssetsManager/lan/routes/metadata.py
pyright AssetsManager/application/search_service.py
git diff --check
```

结果：

```text
All checks passed
0 errors, 0 warnings, 0 informations
退出码 0
```

## 4. 本阶段尚未完成

### 4.1 Search API 仍有两个层次

详细 API 已建立，但三个旧 list API 仍然无法让调用方区分：

```text
empty
unavailable
error
```

这是有意的兼容阶段状态，不应在没有 desktop/插件消费者审查前直接改变返回类型。

### 4.2 LAN 错误 HTTP 策略尚未定版

当前 `include_status=1` 只提供结构化状态，默认仍以 200 + `results/count` 兼容返回。后续要单独决定：

- 哪些 source failure 应继续 200 + degraded；
- 哪些 session/ownership/schema failure 应返回 500/503；
- 是否要引入稳定的 HTTP error code 与 request correlation id；
- 是否需要版本化 opt-in 响应。

本阶段没有把原始 SQLite exception 文本返回给 LAN 客户端。

### 4.3 raw connection 收口仍未完成

根据并行审查 C，当前仍不能把：

```python
allow_unmanaged: bool = True
```

直接改成 `False`。仍存在：

- raw `ProjectData` / `TagStore` / `DirectoryCache` 构造；
- raw Auth/Share/Tag/Metadata/AssetIndex/PluginMetadata repository；
- `AuthService(..., session=None)` / `ShareService(..., session=None)`；
- `ProjectService` 内部 `DirectoryCache(db_conn)`；
- benchmark、performance、历史 fixture；
- 第三方/历史插件间接使用旧 controller/repository 的可能性。

当前应将工程状态记录为：

```text
G3e：调用点显式化完成
G3e+：raw connection 最终迁移未完成
```

## 5. 长期任务规划

### L1：Search status contract 收口

1. 为 `SearchStatus` 和稳定 error code 写 API/版本文档；
2. 对 `/api/search?include_status=1` 增加客户端兼容矩阵；
3. 明确 `degraded`、`partial`、`path_rejected` 的 HTTP 映射；
4. 将 route detailed projection 抽成独立 DTO，避免 metadata route 继续承载过多投影逻辑；
5. 增加 scanner/indexed 双失败、session closing、ownership failure、schema failure 的 HTTP 回归。

### L2：canonical raw-shaped constructor 迁移

按以下顺序，不要跳步：

```text
ProjectService 内部 DirectoryCache(db_conn) → 显式 session
→ ProjectData/TagStore session-bound 构造
→ Auth/Share service 强制 canonical session
→ repositories 增加 session/root-bound 入口
→ historical fixture/benchmark 移入 test-only legacy adapter
→ 第三方/历史插件兼容矩阵
→ 最后 allow_unmanaged 默认切换 False
```

### L3：raw compatibility 可观测与禁止新增

- 将 `allow_unmanaged=True` 限制为明确 legacy adapter/test/migration 边界；
- 为 raw repository constructor 增加静态扫描清单；
- canonical production graph 不再新增 `session=None`；
- 插件 API 不暴露 SQLite connection，只提供 typed metadata/tag ports；
- 在默认切换前建立 unmanaged/managed/foreign-root/closed/session-closed 全矩阵。

### L4：完整工程门禁

继续保持：

```text
WebUI/E2E/tmp 保护域只读
不自动 staging/commit
不 reset/checkout/clean
不宣称整个项目完成
```

在 G9 后再次执行：

```text
python -m pytest -q --tb=short tests/core tests/unit tests/integration tests/desktop tests/lan
ruff check AssetsManager tests
pyright
git diff --check
```

只有全量证据和未决风险列表同时更新后，才进入下一长期切片。

## 6. 当前质量判断

本阶段的新增行为已有定向证据，旧返回合同和 LAN 默认 JSON 仍通过回归；但项目仍处在多会话 dirty 工作区，且 raw connection、第三方插件、WebUI/E2E 未完成统一收口。

因此本报告结论是：

> SearchResultSet 与 LAN opt-in 状态层已完成本阶段实现与验证；AssetsManager 项目整体仍未完成，后续必须继续按 L1→L4 的顺序深审和迁移。
