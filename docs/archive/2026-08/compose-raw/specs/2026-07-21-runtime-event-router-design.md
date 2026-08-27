# Runtime Event Router 设计规范

## [S1] 目标与范围

为每个 `LibraryRuntime` 建立独立的 `RuntimeEventRouter`，把当前库的
session-scoped `DomainEvent` 转换为可供 Desktop projection、LAN realtime
和后续 WebUI provider 消费的不可变 `InvalidationEvent`。

本规范只覆盖事件接收、session 过滤、projection domain 映射、epoch/revision
和订阅生命周期；不实现 WebSocket bridge、HTTP revision endpoint 或 React
realtime provider。

## [S2] 所有权与拓扑

`ApplicationBootstrap.runtime_for(session)` 创建并拥有一个
`LibraryRuntime`。每个 Runtime 创建一个 `RuntimeEventRouter`，Router 只在
Runtime 存活期间订阅全局 `EventBus`。Router 不拥有 session、数据库或应用
服务，也不负责关闭 Runtime。

数据流如下：

```text
DomainEvent
    ↓ global EventBus
RuntimeEventRouter(session filter + mapping)
    ↓ accepted InvalidationEvent
Desktop / LAN / future WebUI subscribers
```

Runtime 关闭时，Router 必须先停止接受新事件并关闭全部 EventBus subscriptions；
之后 Runtime 才能完成自己的 adapter cleanup。Router 的关闭必须幂等。

## [S3] 公共事件模型

新增 `ProjectionDomain` 字符串枚举，值固定为：

```text
files | tree | home | project_detail | metadata | tags
```

新增 frozen `InvalidationEvent`：

```python
@dataclass(frozen=True)
class InvalidationEvent:
    epoch: str
    revision: int
    domains: tuple[ProjectionDomain, ...]
    paths: tuple[str, ...]
```

`domains` 保持稳定的映射顺序并去重；`paths` 为相对当前
`LibrarySession.root` 的 POSIX 风格路径，保持输入顺序并去重。无具体资产路径
的 catalog event 使用空 tuple。不得携带数据库连接、绝对路径、用户凭据或
repository record。

## [S4] 事件映射与过滤

Router 只订阅以下五类 session-scoped events：

| DomainEvent | Projection domains |
|---|---|
| `FileSystemChanged` | `files`, `tree`, `home`, `project_detail` |
| `AssetTagsChanged` | `metadata`, `tags`, `project_detail`, `home` |
| `TagCatalogChanged` | `tags`, `home` |
| `AssetNotesChanged` | `metadata`, `project_detail` |
| `AssetUrlsChanged` | `metadata`, `project_detail` |

事件只有同时满足以下条件才被接受：

1. `event.session_token == runtime.session.event_token`；
2. `event.library_root` 解析后等于 `runtime.session.root`；
3. Router 尚未关闭；
4. 映射结果至少包含一个 projection domain。

错误 token、错误 root、空 session identity、未知 DomainEvent，以及 legacy
无 session 的 `TagsChanged`、`NotesChanged`、`UrlsChanged` 必须静默忽略，且
不得增加 revision 或调用 subscriber。

## [S5] 路径规范化

`FileSystemChanged.paths` 与 `old_paths`、`AssetTagsChanged.file_path`、
`AssetNotesChanged.file_path`、`AssetUrlsChanged.file_path` 都必须先相对化：

- 输入可为绝对路径或相对路径；
- 结果必须使用 `/` 分隔符；
- 结果不得以 `../` 逃逸 library root；
- root 本身归一化为空路径并被忽略；
- 同一事件中的重复路径只保留第一次出现；
- `FileSystemChanged` 合并 `paths` 后再合并 `old_paths`，保持确定性顺序。

如果路径无法安全归一化，整个事件忽略，不产生部分 invalidation。

## [S6] Revision 与 epoch

Runtime 的 `epoch` 唯一标识一次 Runtime 生命周期。Router 接受事件后调用
Runtime 的 revision allocator；revision 严格单调递增，且每个 accepted event
只增加一次。被过滤、关闭或路径无效的事件不增加 revision。

生成的 `InvalidationEvent` 必须携带生成当时的 epoch 和 revision。Runtime
重开同一 library root 时必须获得新 epoch；旧 Router 的事件不得进入新 Runtime。

## [S7] 订阅与错误隔离

`RuntimeEventRouter.subscribe(handler)` 返回可幂等关闭的 EventSubscription。
同一 handler 可订阅多次，按订阅顺序分别调用。关闭 subscription 后不再调用该
handler；Router close 后关闭所有 subscriptions 并拒绝新的 subscription。

subscriber 抛出的异常只能被 Router 记录/隔离，不得阻止其它 subscriber，也不得
反向传播到 EventBus 的 DomainEvent publisher。

## [S8] Runtime 集成与关闭顺序

`LibraryRuntime` 暴露 `event_router`，并在创建时完成 Router 订阅。Runtime
关闭时顺序固定为：

```text
mark router closed
→ unsubscribe EventBus handlers
→ drain/finish Router callbacks
→ close runtime-owned adapters
```

Router 不得在 Runtime close 后继续产生 callback。若 Runtime adapter cleanup
失败，Router 仍必须保持关闭状态，后续 Runtime close 可按 Task 6 的 retry
语义重试 adapters，但不会重新订阅旧 Router。

## [S9] 测试与验收标准

必须覆盖：

- 五类 session-scoped event 的完整 mapping；
- 多 domain 稳定顺序与路径归一化/去重；
- wrong token、wrong root、legacy unscoped event、未知 event 全部忽略；
- accepted event revision 单调递增，ignored event revision 不变；
- 每个 Runtime 独立 epoch 和 Router，旧 Runtime event 不污染新 Runtime；
- 多 subscriber 顺序、单个 subscriber 异常隔离、subscription close；
- Router close 后不再 callback，重复 close 幂等；
- Runtime close 与现有 adapter cleanup retry/lifecycle tests 兼容。

验收命令：

```text
python -m pytest tests/integration/test_runtime_events.py -q
python -m pytest tests/integration/test_runtime_events.py tests/integration/test_event_publishing.py -q
python -m pytest tests/unit/test_bootstrap.py tests/unit/test_library_runtime.py tests/integration/test_library_service.py -q
```

## [S10] 非目标与后续接口

本阶段不改变 EventBus 的全局发布 API，不实现 LAN WebSocket 消息，不定义
HTTP snapshot/revision endpoint，不改动 React 状态管理。Task 10 将消费
`InvalidationEvent`，负责 authenticated WebSocket admission、`runtime_ready`
和 `projection_invalidated` DTO；Task 11+ 再决定客户端 snapshot/gap recovery
策略。
