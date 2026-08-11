# 信号/事件系统（04-events-signals.md）

> 审查日期：2026-08-11 · 工作区实况 · 全部发布/订阅点经 grep 交叉验证

## 1. 事件总线机制（domain/event_bus.py）

- 单例：`get_event_bus()`（双重检查锁，tests/conftest 每测试重置 `_eb._instance`）
- 线程安全：内部 `threading.Lock`；`publish` 锁内快照 handler 列表、锁外同步调用；单 handler 异常 `_log.exception` 隔离，不阻断后续
- 订阅：`subscribe()` 返回幂等 EventSubscription；`subscribe_weak()` 用 `weakref.WeakMethod`（owner 回收自动退订）
- 无事件层级路由：严格按 `type(event)` 精确匹配（无基类通配）

## 2. 领域事件完整清单（domain/events.py，19 个 frozen dataclass）

### A. 会话级事件（带 session_token+library_root → 投影路由）

| 事件 | 发布点 | 投影域 |
|---|---|---|
| LibraryOpened | library_service.py:554 | （无订阅者，仅记录） |
| FileSystemChanged | file_operation_service.py:378、shop_service.py:226 | FILES, TREE, HOME, PROJECT_DETAIL, FAVORITES |
| AssetTagsChanged | tag_service.py:153 | METADATA, TAGS, PROJECT_DETAIL, HOME |
| TagCatalogChanged | tag_service.py:165、file_operation_service.py:961 | TAGS, HOME |
| AssetNotesChanged | metadata_service.py:172 | METADATA, PROJECT_DETAIL |
| AssetUrlsChanged | metadata_service.py:181 | METADATA, PROJECT_DETAIL |
| ShareChanged | share_service.py:180 | SHARES |
| FavoritesChanged | favorite_service.py:82 | FAVORITES |
| UserChanged / InviteChanged | auth_service.py:253,261,272,279 / 254,288,300 | USERS |
| ActivityChanged | order_service.py:132、integrity:260、maintenance:294、lan/_helpers.py:65 | ACTIVITY |
| PresenceChanged | lan/_helpers.py:89 | ONLINE_USERS |
| ShopItemChanged | shop_service.py:232 | SHOP |
| ShopOrderChanged | order_service.py:136 | ORDERS |
| QuotaChanged | order_service.py:141、quota_service.py:73 | QUOTA |

### B. 桌面遗留事件（无 session_token → 桌面面板直接消费）

| 事件 | 发布点 | 消费方 |
|---|---|---|
| FileRenamed | file_operation_service.py:473,554 | 桌面（事件桥/面板） |
| FileDeleted | :623,690 | 桌面 |
| FileCreated | :398,584,652 | 桌面 |
| FileCopied | :506 | 桌面 |
| TagsChanged | tag_service.py:206,221,233,245,260 | 桌面（info 等） |
| NotesChanged / UrlsChanged | metadata_service.py:233 / 251,263 | 桌面 |

## 3. 投影路由（application/runtime_events.py）

- **ProjectionDomain**（14 域）：FILES/TREE/HOME/PROJECT_DETAIL/METADATA/FAVORITES/TAGS/SHARES/USERS/ACTIVITY/ONLINE_USERS/SHOP/ORDERS/QUOTA（前端另有 `stats` 域仅前端存在）
- **EVENT_DOMAINS 映射**（:80-102）：14 类会话事件 → 域元组（见上表）
- **InvalidationEvent**（:52-57）：`{epoch: str, revision: int, domains, paths}` frozen
- **构造**：LibraryRuntime 创建（runtime.py:32），构造时对全部 EVENT_DOMAINS 事件 `bus.subscribe(self._on_event)`（:121-122）
- **会话隔离**（_dispatch_event :217-246）：校验 `session_token == runtime.session.event_token` + library_root resolve 一致；`_normalize_path`（:141-151）归一化根内 POSIX 相对路径，越界丢弃
- **revision**：`runtime.next_revision()`（runtime.py:83-88，加锁单调）
- **订阅/关闭**：subscribe 拒绝已关闭 router；三态 `accepting → closing → drained`；close 等待 in-flight 归零；`defer_after_drain` 延后回调内清理

## 4. WebSocket 协议

**连接**：`GET /ws`（api.py:291）要求 `capabilities.realtime`；query token 一律 401；凭证=Authorization Bearer 或 lan_token cookie；`_authorization_validator` 按 principal 类型绑定规范身份；**容量 50**（超限 1013）。

**消息类型**：
| 消息 | 结构 | 时机 |
|---|---|---|
| `runtime_ready` | `{type, epoch, revision}` | 握手基线（websocket.py:112-113），finish_admission 屏障后放行广播 |
| `projection_invalidated` | `{type, epoch, revision, domains[], paths[]}` | 领域事件经 RuntimeEventRouter → api.py on_invalidation → broadcast |

**心跳**：服务端每 30s ping（序列号 payload），10s 未 pong 即 evict；客户端 PING/PONG 原样回。

**广播上限**：`MAX_BROADCAST_FRAME_BYTES = 1MB`；超限带 paths → 二分截断前缀（95% 预算，`truncated_broadcast_frames` 计数）；无 paths 或截到 0 → 丢弃（`dropped_broadcast_frames` 计数）——**不静默丢**。

**身份吊销**：`revoke_authority`（ws.py:333-368）原子变更+驱逐该 authority 全部 socket（users toggle 禁用用户时使用）；`close_all` 排水关闭。

## 5. 前端消费端（webui）

**RealtimeContext**（stores/RealtimeContext.tsx）：
- cursor `{epoch, revision}`；`enabled = capabilities.realtime`；identity 字符串（身份代际+principal 组成，变化即清 cursor 重建）
- **onEvent**：`runtime_ready` → epoch 变更/身份重置 → `recover(true)`；`projection_invalidated` → asEvent 白名单校验（15 域+paths 字符串数组）→ **缺口检测**：`revision > current+1` → 记录 recoveryIntent 并 recover()；`revision <= current` 丢弃
- **recover()**（:89-144）：GET `/api/revision`（权威快照）→ `responseLeavesGap` 重试一次 → `cursorAdvancedDuringRecovery` 重启 → 游标稳定后 `notify(null)`（全量通知所有注册者重取）
- `registerInvalidation(domains, cb)`：Map 注册表，identity 绑定，返回 unregister

**useInvalidation**：callbackRef 保持最新；domains 变化重注册；断线恢复后各消费方收到 `event === null` 回调自行全量重取（BrowsePage/GalleryHomePage/useFavorites/useSearch/useCommerce* 均此模式）。

**useWebSocket**：指数退避重连 `min(1000*2^retry, 30000)`；`WebSocketTransportHost` 单实例 transport 多消费者 fanout（单消费者异常隔离）。

## 6. 桌面 Qt 信号体系

| 层 | 机制 |
|---|---|
| signal_bus（7 信号） | directory_changed/file_focused/refresh_requested/theme_changed/language_changed/sidebar_depth_changed/ui_scale_changed——低频协调用总线，高频逐文件事件走直连 |
| 域事件桥 | `_event_bridge.py` DomainEventSubscription（EventBus 弱订阅→Qt 信号 Queued）；RuntimeEventSubscription（runtime.event_router → QueuedConnection） |
| 模型信号 | FileSystemModel（scan_*/state_changed/dir_size_ready）；ThumbnailLoader.thumbnail_ready |
| 主题链 | themes.set_theme → bus().theme_changed → WindowCoordinator.on_theme_refresh（淡入淡出+图标重着色）→ 各面板 _on_theme_changed → grid 全纹理失效重建 |
| 订阅生命周期 | PanelContent.shutdown 统一关闭域订阅与总线连接；TabbedDialog showEvent/closeEvent 挂/拆 |

## 7. 事件→行为的完整链路示例（以文件操作+浏览为例）

```
用户粘贴文件 → _actions.py（桌面）→ FileOperationService.move_to_directory
  → 文件系统变更（写锁外 IO）→ 索引刷新 + reconciliation enqueue
  → _notify_session_projection → EventBus.publish(FileSystemChanged)
  → RuntimeEventRouter（校验会话）→ InvalidationEvent(epoch, rev+1, [FILES,TREE,...], paths)
  → lan/api.py → WS broadcast "projection_invalidated"
  → 前端 RealtimeContext：revision 前进 → notify → BrowsePage useInvalidation 回调
  → 按 paths 局部刷新（GET /api/files）＋ 桌面 file_list 500ms 防抖刷新（同一事件双通道）
```
