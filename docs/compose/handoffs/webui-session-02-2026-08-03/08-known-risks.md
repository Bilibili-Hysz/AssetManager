# 08 — 已知风险与禁止误判

## P1：状态文档与实现边界

### G6-5 不能无条件 PASS

当前 G6-5 代码已提交，但独立复核发现数据删除竞态、后台 lease 长时间持有、线程启动失败回滚缺失和缩略图 key 对抗性测试不足。WebUI 会话不需要等待这些问题才能补前端测试，但任何总体验收报告都要保留 blocker。

### 旧测试计数不能直接复用

不同报告来自不同时间、不同工作树和不同测试选择。当前 2026-08-03 WebUI 实测是 37 files / 292 tests；2026-08-04 P0-3 收口后 46/343；P1 补充后 55 files / 404 tests；后续报告必须带命令和日期。

## P1：认证与实时安全

- WebSocket query `token`/`key` 被生产 route 拒绝；不要为了“让连接成功”恢复 query token。
- 同源 HttpOnly cookie 是浏览器 session 边界；不要把 token 放进 localStorage、URL 或 React state。
- capability 是服务端返回的 UX/协议信号，但每个 route 仍需服务端重新验证；前端隐藏按钮不是安全边界。
- share token/cookie 与 LAN auth cookie 是两套语义；分享页面不能把分享密码当成普通登录密码。
- `runtime_ready` 和 `projection_invalidated` 都可能出现 cursor 变化；必须处理 epoch reset、revision gap 和旧身份。

## P1：数据一致性与旧请求

- Realtime event 的 `paths` 不是完整快照；收到事件就 refetch，不能只修改本地数组。
- 搜索、目录切换、identity 切换、invalidation refetch 之间存在交错；使用 generation/AbortController 防止旧结果覆盖新状态。
- `thumbnail_url` 可能为空或返回失败；页面需要 broken image、loading 和 fallback。
- 下载是 Blob/流式响应，不要假设有 `Content-Length`；无长度时仍要显示可用的 indeterminate progress。

## P1：文档与代码差异

- `docs/lan-security.md` 的公开路径表述与 `AssetsManager/lan/routes/system.py` 对 `/api/tunnel/status` 的 admin 要求不完全一致；前端按实际 403 处理，后端文档应另行修订。
- **path 双重解码风险**：aiohttp `{path:.*}` 路由的 `match_info` 已做一次 percent-decode，后端 handler 又 `unquote()` 一次。对普通中文/空格/斜杠无影响，但对文件名含字面 `%`（如 `100%2F50.txt`）时前端 `encodeURIComponent`（`%`→`%25`）经两次解码会还原成 `/`，破坏文件路径。前端按当前契约正常编码，此问题属后端解码层，需 Desktop/LAN 线复核并更新 `tests/lan` 公共契约后再修复。
- `task-14-browser-realtime-acceptance.md` 和 `realtime-dataflow-hardening.md` 的验证数字是历史快照；不要在新报告中无日期引用。
- `architecture.md` 的总体架构是已收口方向，但它不能替代当前运行命令或真实跨端证据。

## P2：测试覆盖风险

- API 工厂方法级契约测试已补（2026-08-04，8 文件 37 用例），但真实网络层、非 2xx 分支和各 route 的权限/能力矩阵仍主要靠 `tests/lan`。
- `ContextMenu`、`Modal`、`ResizablePanel`、`UserManagement` 已补直接行为测试（2026-08-04，24+7 用例），但真实 pointer capture、拖拽与 CSS 布局仍靠 jsdom 近似；`ResizablePanel` 卸载清理缺陷已在测试中发现并修复。
- `TagChip`（7 用例）、`useMediaQuery`（3 用例）、`useDialogFocus`（6 用例）已补基础组件/hooks 行为覆盖。`useMediaQuery` mock `matchMedia`（jsdom 无真实实现），`useDialogFocus` 焦点 trap 在 jsdom 中仅验证逻辑分支（Tab 键序、focus 回归）。
- App 路由组合（公开/受保护/share/未知/Provider）和 i18n key parity（zh/ja vs en）已形成直接门禁（2026-08-04，App 9 用例 + i18n 5 用例）。

## P2：浏览器与性能风险

- jsdom 不能证明真实 CSS 布局、滚动、pointer capture、下载保存、WebSocket 握手和图片解码。
- headless Chromium 临时库不能证明真实 Desktop 主窗口与 LAN 第二客户端的用户旅程。
- 真实图片/目录性能当前缺少固定 manifest、确定性采样、重复运行和硬件元数据；不要仅凭一次本机运行调整阈值。
- Gate 的动画必须尊重 reduced motion，并限制 DOM 节点数量；Browse/FileList 的卡片阵列和缩放动画不能引入无界重排。

## 处理原则

1. 先标证据边界，再决定是否改代码。
2. 先补最小可复现测试，再处理架构级变化。
3. 前端体验变化必须保留权限、错误、焦点、键盘和 stale response 行为。
4. 发现跨表面协议问题时，暂停单方面修复，先更新契约矩阵并让 Desktop/LAN 线复核。

## P2：DeepSeek 计划映射风险

- DeepSeek Docs 的桌面视觉规划已经记录部分 V1 交付，不能把 Qt/QSS 的“已完成”直接当作 WebUI 已完成；必须按 React 组件和浏览器证据重新验收。
- G5-3 批量下载在当前 WebUI 已部分落地，G5-6 主题切换已有基础实现，G5-8 分享创建已有实现；报告应写“部分完成”而不是重复列为纯缺口。
- G5-1 编辑、G5-2 上传和 G5-4 虚拟滚动分别依赖后端契约、权限/存储语义或真实性能数据；不能通过前端假状态抢跑。
- Storefront S1-S4 是未来产品域；价格、支付、订单和社交功能不属于当前 WebUI 第二会话。
- 主题 JSON 双端单一来源是长期方向，当前不要阻塞前端视觉切片等待跨端 token 生成器。
