# 模块排 Bug 清单（module-lan-tools.md · 2026-08-10 P0 第1轮）

> **状态（2026-08-12）**：全部 24 项已修。S1/T1-T4/T8/U1/W2/D1/D2 于 P2 轮修复；**S2-S8/T5-T7/W5-W8/D3-D6 于 2026-08-12 修复**（scanner 取消不发布部分索引+锁化+invalidate、tunnel dev 路径 3 级跳转 bug+URL 锚定+stop 幂等、ws 心跳生命周期+authority 清理、dto 深度截断+type 契约对齐）。验证：3145 passed。
> **D4 契约决策**：TreeItemResponse 的 type 只允许 "dir"（缺失默认 dir，显式 file/未知拒绝）——由服务端构造，降级会掩盖内部 bug（test_public_contracts 断言）。

> 来源: 只读探索代理审计，行号经源码核对。修复前需第二子代理复核真实性。


# LAN 工具链缺陷审计清单（只读审计，未修改仓库代码）

范围: AssetsManager/lan/scanner.py, tunnel.py, utils.py, ws.py, dto.py
审计日期: 2026-08-10

## scanner.py — DirectoryScanner

### S1 [中] start_background_scan 非原子 check-then-set（scanner.py:24-30）
- 描述: `if self._scanning: return` 与 `self._scanning = True` 之间无锁保护。
- 触发/复现: 两个线程同时调用 start_background_scan()（例如启动流程与状态页并发触发），会同时启动两个扫描线程；两次 `self._index = index` 互相覆盖，`is_scanning` 语义短暂失真，重复占用 I/O。
- 修复建议: 将检查+置位放入 `self._lock`（或 threading.Event/原子标志）内完成。

### S2 [低] 扫描无取消机制、大目录期间新旧索引并存（scanner.py:32-63）
- 描述: `os.walk` + 逐文件 `os.stat` 全量同步扫描，无取消信号；完成前索引一直是旧值，且新索引构建期间内存双份。
- 触发/复现: 数十万文件的大库，扫描耗时数分钟；期间 API 始终返回旧索引，且无法中止。
- 修复建议: 使用 threading.Event 支持取消；分批构建（如每 N 文件短暂让出 GIL）；可考虑增量扫描。

### S3 [低] is_scanning() 无锁读取（scanner.py:72-73）
- 描述: `is_scanning()` 直接读 `_scanning`，未在 `_lock` 内；依赖 GIL 才安全。
- 触发/复现: 与 S1 叠加时可能读到陈旧值。
- 修复建议: 统一在锁内读写。

### S4 [低] search() 全量过滤后切片 + 返回共享可变引用（scanner.py:65-70）
- 描述: 先对全索引做 list 推导（O(n) 内存拷贝）再 `[:limit]`；返回的 dict 与索引内对象是同一引用。
- 触发/复现: 索引 10 万条时单次搜索拷贝开销大；若未来某调用方修改返回 dict（如追加字段），会污染内存索引，导致后续搜索结果错乱（当前 search_service 只读，风险潜伏）。
- 修复建议: 命中 limit 即提前终止；返回深拷贝或冻结结构（MappingProxyType/dataclass）。

### S5 [低] 索引无刷新/失效机制
- 描述: 索引只在启动时构建一次（server.py:1316），库内容变化后搜索结果永久陈旧。
- 触发/复现: 启动后新增/删除文件，/api/search 的 scanner 来源结果不变。
- 修复建议: 提供 rescan/触发式刷新（文件监听或定时重建）。

### S6 [低] search(query) 未做 None/类型防护（scanner.py:67）
- 描述: `query.lower()` 在 query 为 None 时抛 AttributeError（当前路由保证字符串，防御不足）。
- 修复建议: `q = (query or "").lower()`。

### S7 [低] os.walk 默认静默跳过无权限目录（scanner.py:37-39）
- 描述: 未传 onerror，遇到不可读目录静默跳过，索引与磁盘不一致且无日志。
- 修复建议: `os.walk(self._root, onerror=lambda e: _log.warning(...))`。

### S8 [低] _db 参数死代码（scanner.py:17-19）
- 描述: `db_conn` 保存后从未使用。
- 修复建议: 删除或接入索引持久化。

## tunnel.py — TunnelManager / 下载 / 查找

### T1 [高] 下载无校验、无超时、残留半成品文件（tunnel.py:26-37）
- 描述: `urllib.request.urlretrieve` 无 timeout（可无限挂起）；下载后无 checksum/大小校验，也无 `--version` 冒烟测试；失败/中断会留下损坏的 exe。
- 触发/复现: 网络抖动或用户中断下载 → shared_dir 留下损坏文件 → `_find_cloudflared` 因 `os.path.isfile` 判定"已安装"，`is_available()` 返回 True，tunnel start 报出难诊断的启动失败；无外网时 urlretrieve 可能长时间挂起 UI 线程。
- 修复建议: 下载到唯一临时名 + 校验（sha256 与官方预期值或至少大小）+ `cloudflared --version` 验证通过后原子 rename；设置 socket 超时；失败时清理临时文件。

### T2 [中] 并发下载无锁（tunnel.py:83-92 与 26-37）
- 描述: `ensure_available()`/`is_available()` 可从多线程调用，两处同时 urlretrieve 同一 dest，互相覆盖导致文件损坏。
- 触发/复现: 设置对话框与开机检查并发触发。
- 修复建议: 模块级 threading.Lock 串行化下载，下载期间 is_available 视为不可用。

### T3 [中] 进程崩溃无监控、无自动重启、状态陈旧（tunnel.py:156-191）
- 描述: cloudflared 崩溃退出后仅 `is_running` 变 False；`_process` 引用未清、`_public_url` 残留；没有任何监视线程。ShareManager 的 `tunnel_running=True` 状态会一直保留到用户手动操作。
- 触发/复现: cloudflared 被外部杀掉或自身崩溃 → 管理端仍显示隧道"运行中"，public_url 失效，直到 stop/restart。
- 修复建议: 增加守护/监视线程（轮询 poll()），崩溃时回调状态变化并支持指数退避自动重启；清理 _process/_public_url。

### T4 [中] start() 并发竞态可能误杀正在启动的隧道（tunnel.py:104-107）
- 描述: 第二个线程在进程已启动但 URL 尚未解析时调用 start()：`is_running` 为 True → 直接 `return self._public_url`（此时为 None）→ 调用方把 None 当失败 → 执行 stop() 杀掉第一个隧道。
- 触发/复现: 设置面板与分享管理器同时触发"开启公网链接"。
- 修复建议: start() 内加锁；is_running 且 URL 未就绪时等待 `_ready`（带超时）再返回。

### T5 [低] _find_cloudflared dev 模式路径多跳一级（tunnel.py:56-59）
- 描述: `src_dir` 是 `AssetsManager/lan`，`join(src_dir, "..","..","..", exe)` 定位到项目根的上层目录（如 `...\Projects\cloudflared...`），而非项目根/源码同级；正常 dev 布局几乎永远命中不了。
- 触发/复现: 把 cloudflared 放到项目根目录后 is_available() 仍返回 False。
- 修复建议: 改为 `src_dir/../..`（或显式规范化的候选目录列表）。

### T6 [低] URL 解析正则局限且未锚定（tunnel.py:137）
- 描述: 仅匹配 `[a-z0-9-]+\.trycloudflare\.com`，`re.search` 不锚定 token 边界；未来自定义域名/新 quick tunnel 域名无法解析，错误行也可能产生假阳性。
- 修复建议: 行内锚定（如 `(?:^|\s)(https://...\.trycloudflare\.com)(?:\s|$)`），域名列表可配置。

### T7 [低] stop() 的 RuntimeError 会泄漏；端口无类型校验（tunnel.py:156-183, 98-100）
- 描述: start() 超时路径调用 stop()，若进程杀不死则 RuntimeError 向上抛（manager 已 catch，但语义应内部消化）；`local_port` 未校验，非 int 时生成畸形 URL/TypeError（list 参数无 shell 注入风险，仅健壮性问题）。
- 修复建议: stop() 内部吞掉并记录"残留进程"警告；start() 前校验端口为 1-65535 int。

### T8 [低] ensure_available 无运行验证（tunnel.py:83-92）
- 描述: 下载成功后直接返回路径，不验证可执行性；被杀毒软件拦截/架构不符时直到 start 才暴露。
- 修复建议: 下载后执行 `--version` 验证。

## utils.py

### U1 [中] get_local_ip 多网卡场景错误 + 无默认路由时回退 127.0.0.1（utils.py:14-29）
- 描述: 通过 connect(("8.8.8.8",80)) 取默认路由网卡 IP：VPN/WSL/多网卡机器会返回虚拟网卡地址（LAN 客户端不可达）；纯局域网（无默认路由）直接回退 127.0.0.1，共享 URL 完全不可用。
- 触发/复现: 机器同时有以太网+WiFi，或挂了 VPN，或离线局域网环境启动 LAN 共享。
- 修复建议: 枚举所有 AF_INET 接口，优先私网地址并排除虚拟网卡；无默认路由时不要回退回环，改取第一个可达私网地址。

### U2 [低] 无 IPv6；token 秒级时间戳（utils.py:14-29, 44-46）
- 描述: 仅 IPv4；`str(int(time.time()))` 秒级精度，同一秒生成的 token 相同（无安全影响）；跨时区/时钟偏差大的客户端可能提前/延后过期（取决于服务端校验逻辑，建议服务端用容差窗口）。
- 修复建议: 可选支持 IPv6；服务端校验使用 24h 容差。

### U3 [无] 端口探测竞态
- 描述: utils.py 中不存在任何端口探测代码（无 connect_ex/check_port），该检查点"无"。

## ws.py — WebSocketManager

### W1 [中] finish_admission 发送基线无超时（ws.py:393-410）
- 描述: `await ws.send_json(payload)` 无 wait_for；慢速/卡死客户端会让路由协程无限阻塞，且 admission 未完成期间该 socket 的广播每次都要等 5s 超时。
- 触发/复现: 客户端 TCP 窗口满且不再读数据，连接建立后发送初始 payload。
- 修复建议: `await asyncio.wait_for(ws.send_json(payload), WS_OPERATION_TIMEOUT)`，失败即 evict。

### W2 [中] broadcast 的 json.dumps 无防护、无消息大小限制（ws.py:462-503）
- 描述: `json.dumps({"type":..., **(data or {})})` 在 try 之外，data 含 bytes/datetime/自定义对象时 TypeError 直接抛给调用方；api.py 有 done-callback 兜底，但 server.py:944 的包装路径异常可能无人消费（asyncio exception never retrieved）；同时 payload 无上限，超大帧拖慢慢速客户端。
- 触发/复现: 任一事件数据含非 JSON 可序列化字段；或 payload 数 MB 时对慢客户端 send 阻塞 5s 后被 evict。
- 修复建议: broadcast 内部 try/except 记日志；限制单帧大小（如 1MB），超限降级为截断/拒绝并告警。

### W3 [中] add/_authorize_for_authority/_authority_ready 无超时等待（ws.py:101-145, 353-375）
- 描述: revoke 流程异常/持有锁不释放时，`transition.ready.wait()` 与重试循环可无限等待，路由协程挂死；客户端连接永不关闭。
- 触发/复现: revoke_authority 回调（如 DB 卡死）长时间不返回，期间新连接 add()。
- 修复建议: 等待加 wait_for 超时，超时按拒绝处理并关闭连接。

### W4 [低] close_all() 同步路径无锁修改共享状态（ws.py:512-524）
- 描述: `self._accepting = False` 与逐 lease `active=False` 未持锁，与并发 add()/broadcast() 存在数据竞争（teardown 场景通常已停止接收新连接，风险较低）。
- 修复建议: 在 `_close_all` 内统一持锁修改。

### W5 [低] 心跳任务生命周期竞态（ws.py:417-424, 135-136）
- 描述: `_heartbeat` 在 `_clients` 为空时置 `_heartbeat_task=None` 后 return；若 add() 恰在此窗口创建新任务，会短暂存在两个心跳任务（一方随即退出，无害但可读性差）。
- 修复建议: 由 add() 统一管理任务引用，或心跳退出前再次确认。

### W6 [低] _authority_locks/_authority_transitions 无界增长（ws.py:70-72）
- 描述: 以 authority（用户 id 等）为键的字典只增不减（close_all 才清空），长时间运行+大量不同用户连接时内存缓慢泄漏。
- 修复建议: 无 lease 引用时回收对应 authority 条目。

### W7 [低] PONG 依赖消息循环及时处理（ws.py:412-415, 194-198）
- 描述: 心跳 pong 需经路由 `async for msg` 循环分发；客户端高频发消息导致 PONG 排队延迟时，10s 心跳超时可能误杀健康客户端。
- 修复建议: 心跳容忍度放宽（如 2 个周期）或按客户端消息积压量调整。

### W8 [低] 慢客户端发送期间持有 lease.lock（ws.py:472-490）
- 描述: send_to 在 lease.lock 内 await send_str；同一 authority 的其它客户端广播被串行拖慢（有 5s 兜底，影响有限）。
- 修复建议: 发送前先取快照，不在锁内 await I/O（或使用每连接发送队列+背压）。

## dto.py

### D1 [中] from_record 按必填索引，缺字段即 KeyError 500（dto.py:83-86, 100-104）
- 描述: TypedDict 均声明 total=False（字段可选），但实现用 `record["id"]`/`record["username"]`/`record["is_active"]` 直接索引；任一字段缺失时 /api/users、/api/invites、/api/auth/login 整体 500。
- 触发/复现: 数据库迁移/旧库缺列，或 auth 服务返回精简记录。
- 修复建议: 改用 `.get()` + 显式校验与默认值，缺失时抛业务化错误而非 KeyError。

### D2 [中] _as_int/_as_float 类型错误崩溃或静默截断（dto.py:25-30）
- 描述: `int()`/`float()` 对非法输入（ISO 时间字符串、带时区字符串、None）抛 ValueError 500；对 1.5 静默截断为 1（id 精度丢失）。
- 触发/复现: created_at 某条记录被写成文本格式，或 id 存为 REAL。
- 修复建议: try/except 校验；整数语义用 `int(round(x))` 并拒绝非数值字符串。

### D3 [低] TreeItemResponse 递归无深度限制、children 类型未校验（dto.py:134-152）
- 描述: 递归构造无深度上限，极端深目录树触发 RecursionError 导致 /api/tree 500；children 若为 dict（单子节点）会迭代出键字符串导致 TypeError。
- 触发/复现: 构造 1000 层深的嵌套 children。
- 修复建议: 限制深度或改迭代式构建；children 非 list 时明确报错。

### D4 [低] 非 "dir" 类型直接 ValueError（dto.py:140-148）
- 描述: type 字段只允许 "dir"，未来树加入文件节点（type="file"）时整个接口崩溃（当前 producer 仅目录，风险潜伏）。
- 修复建议: 按白名单映射或允许 "file"，保持向后兼容。

### D5 [低] StatsResponse 显式 None 字段崩溃（dto.py:167-173）
- 描述: `record.get("connections", 0)` 在值显式为 None 时 `int(None)` 抛错（status() 当前总给数值，防御不足）。
- 修复建议: `value or 0` 兜底。

### D6 [低] 时区无处理/无契约（dto.py:83-104）
- 描述: created_at 按 float（UTC epoch）直传，无时区标记与转换；客户端若按本地时区渲染会整体偏移；RuntimeCursorResponse.epoch 为不透明字符串，缺乏语义契约。
- 修复建议: 文档化"epoch 秒 UTC"，或统一输出带时区的 ISO8601。

### D7 [无] 金额精度
- 描述: 本文件无金额字段（金额相关在 order_repository 以 amount_cents 整数存储，不在此范围），该检查点"无"。
