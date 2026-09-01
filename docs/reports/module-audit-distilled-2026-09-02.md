# 模块审计底稿蒸馏（module-audit-distilled · 2026-09-02）

> 状态:**现行** · 本文档为 2026-09-02 收敛轮蒸馏产物，取代下列 11 份原件（已归档至 `archive/2026-09/module-audits-superseded/`）：module-assets-p1 / module-commerce-p1 / module-core-db / module-core-store / module-file-ops / module-lan-core / module-lan-routes / module-lan-tools / module-maintenance / module-repositories-p1 / module-runtime · 状态登记:2026-09-02（文档收敛轮）

## 概览

- 来源：2026-08-10~11 的 P0 / P1 轮**行号级**模块排 Bug 审计底稿，共 11 个模块。
- 处置：所有发现项已于 2026-08-12 P2 轮修复，或由后续四轮评审（`desktop-uiux-review` / `webui-review` / `expert-panel-deep-analysis` / `re-audit`）关闭。
- **红线**：原始行号已随代码演化失效，本文档不保留行号，仅保留模块、严重度分布与主题索引，作为历史取证入口；权威现状见 `architecture.md` 与各现行评审基线。

## 模块汇总

| 模块 | 轮次 | 日期 | 状态 | 高 | 中 | 低 | 合计 |
|---|---|---|---|---|---|---|---|
| `module-assets-p1.md` | P1 | 2026-08-11 | 已过期 |  | 10 | 9 | 19 |
| `module-commerce-p1.md` | P1 | 2026-08-11 | 全部已修 | 3 | 6 | 6 | 15 |
| `module-core-db.md` | P0 | 2026-08-10 | 全部已修 |  |  |  | 16 |
| `module-core-store.md` | P0 | 2026-08-10 | 全部已修 |  |  |  | 27 |
| `module-file-ops.md` | P0 | 2026-08-10 | 全部已修 |  |  |  | 22 |
| `module-lan-core.md` | P0 | 2026-08-10 | 已过期 |  |  |  | 0 |
| `module-lan-routes.md` | P0 | 2026-08-10 | 已过期 |  |  |  | 0 |
| `module-lan-tools.md` | P0 | 2026-08-10 | 全部已修 |  |  |  | 24 |
| `module-maintenance.md` | P0 | 2026-08-10 | 全部已修 |  |  |  | 18 |
| `module-repositories-p1.md` | P1 | 2026-08-11 | 已过期 |  | 5 | 10 | 15 |
| `module-runtime.md` | P0 | 2026-08-10 | 全部已修 |  |  |  | 25 |

## 主题索引（保留原始描述性发现标题）

### module-file-ops.md
- 1. [高] 单文件 move 对已存在目标静默覆盖（Windows 同样受影响）
- 2. [中] 跨盘/跨卷移动失败后目标残留部分拷贝
- 3. [高] delete_permanent 非 OSError 异常 → 已删除文件的撤销备份被整体丢弃（数据丢失）
- 4. [中] move 文件已移动但投影/元数据失败 → 事件不发布、UI 与实际不一致
- 5. [中] move 持有 DB 写锁执行文件 IO，长操作阻塞全库写入
- 6. [中] create_folder 缺少库根校验
- 7. [中] delete_permanent/delete_to_trash 允许删除库根本身
- 8. [中] 删除操作断言用 resolve 路径、实际操作用未解析路径
- 9. [低] Windows 保留设备名/结尾点空格/MAX_PATH 无友好处理
- 10. [低] 符号链接策略偏保守（根内指向根外的链接无法移动/删除）
- 11. [高] 撤销删除只恢复文件，不恢复标签/元数据/收藏/缩略图记录
- 12. [中] perform_undo/perform_redo 存在 TOCTOU：文件操作已生效但历史栈未移动
- 13. [中] 批量移动部分成功时撤销记录整体缺失
- 14. [中] 撤销重命名时原位置被重新占用：Windows 卡栈 / POSIX 覆盖
- 15. [低] 撤销失败条目无驱逐机制，栈被毒化
- 16. [低] _make_backup 失败静默，删除对话框承诺可撤销但不兑现；无大小/空间限制
- 17. [中] 批量删除中途非 OSError 异常：部分成功事件已发布但 errors 契约丢失
- 18. [低] 事件发布契约不一致：FileSystemChanged 仅 session 绑定时发布
- 19. [中] 同文件并发操作无互斥；回收站删除与永久删除无串行化
- 20. [低] move 持 DB 写锁执行文件 IO（同 #5，并发影响面）
- 21. [高] unique_destination 在目标目录只读/磁盘满/名称非法时死循环
- 22. [低] 错误分类缺失：errors 仅含 str(exc) 原始文本
- 23. 空选择：无问题

### module-lan-tools.md
- S1 [中] start_background_scan 非原子 check-then-set（scanner.py:24-30）
- S2 [低] 扫描无取消机制、大目录期间新旧索引并存（scanner.py:32-63）
- S3 [低] is_scanning() 无锁读取（scanner.py:72-73）
- S4 [低] search() 全量过滤后切片 + 返回共享可变引用（scanner.py:65-70）
- S5 [低] 索引无刷新/失效机制
- S6 [低] search(query) 未做 None/类型防护（scanner.py:67）
- S7 [低] os.walk 默认静默跳过无权限目录（scanner.py:37-39）
- S8 [低] _db 参数死代码（scanner.py:17-19）
- T1 [高] 下载无校验、无超时、残留半成品文件（tunnel.py:26-37）
- T2 [中] 并发下载无锁（tunnel.py:83-92 与 26-37）
- T3 [中] 进程崩溃无监控、无自动重启、状态陈旧（tunnel.py:156-191）
- T4 [中] start() 并发竞态可能误杀正在启动的隧道（tunnel.py:104-107）
- T5 [低] _find_cloudflared dev 模式路径多跳一级（tunnel.py:56-59）
- T6 [低] URL 解析正则局限且未锚定（tunnel.py:137）
- T7 [低] stop() 的 RuntimeError 会泄漏；端口无类型校验（tunnel.py:156-183, 98-100）
- T8 [低] ensure_available 无运行验证（tunnel.py:83-92）
- U1 [中] get_local_ip 多网卡场景错误 + 无默认路由时回退 127.0.0.1（utils.py:14-29）
- U2 [低] 无 IPv6；token 秒级时间戳（utils.py:14-29, 44-46）
- U3 [无] 端口探测竞态
- W1 [中] finish_admission 发送基线无超时（ws.py:393-410）
- W2 [中] broadcast 的 json.dumps 无防护、无消息大小限制（ws.py:462-503）
- W3 [中] add/_authorize_for_authority/_authority_ready 无超时等待（ws.py:101-145, 353-375）
- W4 [低] close_all() 同步路径无锁修改共享状态（ws.py:512-524）
- W5 [低] 心跳任务生命周期竞态（ws.py:417-424, 135-136）
- W6 [低] _authority_locks/_authority_transitions 无界增长（ws.py:70-72）
- W7 [低] PONG 依赖消息循环及时处理（ws.py:412-415, 194-198）
- W8 [低] 慢客户端发送期间持有 lease.lock（ws.py:472-490）
- D1 [中] from_record 按必填索引，缺字段即 KeyError 500（dto.py:83-86, 100-104）
- D2 [中] _as_int/_as_float 类型错误崩溃或静默截断（dto.py:25-30）
- D3 [低] TreeItemResponse 递归无深度限制、children 类型未校验（dto.py:134-152）
- D4 [低] 非 "dir" 类型直接 ValueError（dto.py:140-148）
- D5 [低] StatsResponse 显式 None 字段崩溃（dto.py:167-173）
- D6 [低] 时区无处理/无契约（dto.py:83-104）
- D7 [无] 金额精度

## 其余模块（仅严重度分布 / 已修合计）

- **module-assets-p1.md**：P1 · 2026-08-11 · 已过期（行号失效，发现项由后续批次关闭） · 高0/中10/低9
- **module-commerce-p1.md**：P1 · 2026-08-11 · 全部已修（2026-08-12 P2 轮，共 15 项） · 高3/中6/低6
- **module-core-db.md**：P0 · 2026-08-10 · 全部已修（2026-08-12 P2 轮，共 16 项） · 合计 16
- **module-core-store.md**：P0 · 2026-08-10 · 全部已修（2026-08-12 P2 轮，共 27 项） · 合计 27
- **module-lan-core.md**：P0 · 2026-08-10 · 已过期（行号失效，发现项由后续批次关闭） · 严重度分布未单列
- **module-lan-routes.md**：P0 · 2026-08-10 · 已过期（行号失效，发现项由后续批次关闭） · 严重度分布未单列
- **module-maintenance.md**：P0 · 2026-08-10 · 全部已修（2026-08-12 P2 轮，共 18 项） · 合计 18
- **module-repositories-p1.md**：P1 · 2026-08-11 · 已过期（行号失效，发现项由后续批次关闭） · 高0/中5/低10
- **module-runtime.md**：P0 · 2026-08-10 · 全部已修（2026-08-12 P2 轮，共 25 项） · 合计 25

## 跨模块高频主题

- **Windows 文件系统边界**：跨盘移动残留、同名静默覆盖、名称校验（file-ops、core-store）
- **并发与锁**：DB 写锁内执行文件 IO、scanner 取消机制缺失、索引无失效刷新（file-ops、lan-tools、runtime）
- **LAN 端点安全**：错误码泄露分享存在性/限额、路由策略契约（commerce、lan-routes、lan-core）
- **状态可见性**：is_scanning 无锁读取、search 返回可变引用（lan-tools）

## 溯源

- 原件：`archive/2026-09/module-audits-superseded/`
- 现行评审基线：`reports/desktop-uiux-review-2026-08-29.md`、`reports/webui-review-2026-08-29.md`、`reports/re-audit-2026-09-01.md`
- 关闭证据：2026-08-12 P2 修复记录 + 上述四轮评审
