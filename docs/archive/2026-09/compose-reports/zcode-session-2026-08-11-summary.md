# ZCode 会话汇总 — 审计遗留项收尾（1a-1e）+ LAN 限流口径修正（2026-08-11）

> **来源会话**：ZCode（deepseek-v4-flash），2026-08-11
> **任务来源**：`opencode-session-2026-08-11-{startup,summary}.md` 的『下一步』第 1、2 项（审计遗留项 + 中危剩余限流项）
> **性质**：全程未产生任何 git commit —— 所有代码改动均处于工作区**未提交**状态（与约 191 个预存修改文件混合）
> **验证基线**：全量 `pytest tests -q` → **2865 passed, 7 skipped, 0 failed**（306s；上一基线 2839，本轮净增 26 个测试）

---

## 1. 本轮完成内容

| 任务 | 内容 | 结果 |
|------|------|------|
| 1a（高） | 查询串 token 认证（`?token=`/`?key=`）全量禁用并删除死代码 | ✅ |
| 1b（高） | `ShareManager.stop()` 失败保留 `_server` 句柄供重试 | ✅ |
| 1c（中） | WebSocket broadcast 超 1MB 帧截断 paths 发送 + 计数（不再静默丢弃） | ✅ |
| 1d（中） | 认证令牌加随机 nonce（消除同秒确定性），verify 兼容旧格式 | ✅ |
| 1e（低） | `_as_int` inf/nan、tool_scheduler 数值参数、`_query_referer_allowed`（随 1a 删除） | ✅ |
| 任务 2（中） | security.py 限流口径：Retry-After 动态计算、get_remaining O(1)、remote None 拒绝、/api/files 仅 GET 跳过 | ✅ |
| 测试缺口 | test_tray QApplication fixture、批量 move 部分成功撤销用例、1d 格式歧义回归 | ✅ |
| 审计闭环 | 复核子代理 4 组全部符合 + 审计子代理复审 → 3 处修复 | ✅ |

## 2. 改动文件清单（全部未提交）

**组 A（1a）**
- `AssetsManager/lan/routes/_helpers.py`：删除 query 分支与 `_query_referer_allowed`、`urlsplit` import；`get_auth_token(request)` 仅剩 Bearer/cookie
- `AssetsManager/lan/server.py`：3 处调用点去掉 `allow_query` 参数（含主中间件 1698 的 `allow_query=path != "/ws"`）
- `AssetsManager/lan/routes/websocket.py`：调用点同步（:98 的 /ws query 拒绝检查保留）
- `tests/lan/test_helpers.py`：2 个 query 测试改写为拒绝断言
- `tests/lan/test_lan_api.py`：query 认证测试改写为 401；另 3 个依赖 `?key=` 的测试（admin context/hash 不泄漏/缓存失效）改为 `Authorization: Bearer` 认证（测试意图保留）

**组 B（1b）**
- `AssetsManager/lan/manager.py`：`stop()` 改 try/except/else（成功才清句柄）；`start()` 入口清理残留句柄；start 失败分支保留 residual（审计修复）；删除未使用的 `self._preflight`（审计修复）
- `tests/unit/test_lan_sharing.py`：重写 stop 重试契约测试

**组 C（1c + 1d）**
- `AssetsManager/lan/ws.py`：`_trim_broadcast_payload` 二分截断 paths（95% 预算）+ `_truncated_broadcast_frames`/`_dropped_broadcast_frames` 计数器 + 只读属性；删除死条件（审计修复）
- `AssetsManager/domain/auth.py`：4 个 generate 函数加 `secrets.token_hex(4)` nonce（`ts.nonce.sig` / `ts.uid.nonce.sig`），4 个 verify 函数兼容新旧格式
- `AssetsManager/lan/utils.py`：`generate_auth_token` 同步加 nonce
- `tests/unit/test_domain_auth.py`（+8：同秒唯一性 + legacy 兼容）、`tests/lan/test_runtime_realtime.py`（+2：截断/丢弃计数）、`tests/lan/test_lan_api.py`（share token 格式断言更新）

**组 D（1e + 任务 2）**
- `AssetsManager/lan/dto.py`：`_as_int` float 分支捕获 OverflowError/ValueError
- `AssetsManager/core/tool_scheduler.py`：args 允许 int/float 并 str() 归一化（拒绝 bool）
- `AssetsManager/lan/security.py`：`retry_after(ip)` 方法（窗口剩余动态计算）、`get_remaining` 先剪枝、`request.remote` 空拒绝 400、`/api/files` 仅 GET 跳过、docstring 注明限流权衡（前置计数 + IP 维度，不做失败计数/用户名级）
- `tests/unit/test_dto.py`、`tests/unit/test_tool_scheduler.py`（新建）、`tests/lan/test_lan_api.py` TestRateLimiter（+2）

**1d 衍生缺陷修复（全量回归暴露）**
- `AssetsManager/application/auth_service.py`：`verify_user_token` 的 DB 查询包 try/except（见第 4 节）
- `tests/integration/test_auth_service.py`（+1 回归）

**测试缺口**
- `tests/unit/test_tray.py`：补 QApplication 初始化（原挂起）
- `tests/integration/test_file_operation_service.py`（+1：moved_pairs 部分成功契约）
- `tests/integration/test_undo_service.py`（+1：批量 move 部分成功撤销完整性）

## 3. 审计闭环

1. **复核子代理**（只读）：4 组落盘状态逐条核对——全部符合方案；test_lan_api.py 双组改动共存无覆盖；`allow_query`/`_query_referer_allowed` 全仓零残留；新旧格式兼容硬要求满足
2. **审计子代理**（只读）：无崩溃/安全绕过/性能回退；指出 2 处需修 + 若干既有模式
3. **主代理修复 3 处**：
   - `manager.py` start 失败分支保留 residual 句柄（原会丢弃残留，失去重试能力）
   - `manager.py` 删除未使用 `self._preflight`（本轮引入）
   - `ws.py` 删除死条件 `frame_size(keep) > MAX_BROADCAST_FRAME_BYTES`（二分不变量保证恒假）

## 4. ★ 重要发现：1d 令牌格式空间歧义（全量回归暴露的真实缺陷）

**现象**：`test_middleware_accepts_plaintext_password` 失败 `sqlite3.OperationalError: no such table: users`（非确定性，概率约 2.3%）。

**根因**：simple token 新格式 `ts.nonce.sig`（3 段）与 user token **旧格式** `ts.uid.sig`（3 段）段数重叠。`auth_service.verify_user_token` 先 `int(parts[1])` 再查 DB——当 simple token 的 nonce（8 位 hex）恰好全为数字时，误入 user token 路径并查询 users 表；无 users 表的库（旧库/骨架测试）直接抛 OperationalError → 500。

**修复**：`auth_service.verify_user_token` 的 `_repo.get_user_by_id` 包 try/except → DB 失败视为"非 user token"（返回 None），调用方回退 password 验证。已补确定性回归测试（monkeypatch repo 抛异常 + 数字 nonce token）。

**教训（沉淀）**：令牌格式演进时，新旧格式的段数空间可能重叠——simple 新(3)=user 旧(3)。后续若再改令牌格式，需先枚举所有 generate/verify 函数的段数组合，避免歧义。

## 5. 未做（有意取舍，审计确认）

- **security.py "成功请求也计数 / NAT 多用户锁死"**：保持前置计数（防暴力必须先限流），"失败才计数"在事件循环 await 间有真实竞态，不做；已在模块 docstring 注明权衡
- **`reqs.pop(0)` O(n²) 剪枝**：既有模式（`is_allowed` 中早已存在），非本轮引入，未改
- **manager.py stop 失败时 failure_reason 被 tunnel_cleanup_failed 掩盖**：旧行为延续，未扩大改动面
- **HEAD /api/files 不再跳过限流**：影响可忽略

## 6. 下一步（按优先级，来自交接文档）

1. **P1 轮**：M6a 资产/索引/缩略图/搜索服务（含 project_data TTL 接入、library_export 上限与并发检测、server.py:1502 fail-closed 无负缓存）、M9 repositories 16 文件 SQL 安全、M6c 分享/商业（配额竞态、订单状态机、金额精度）
2. **P2 轮**：M1 file_list、M2 info/sidebar、M3 dialogs、M4 窗口/dock、M5+M7 controllers/domain（约 121 项低危，见 `docs/reports/module-*.md`）
3. **补测试**：grid scale 重排/省略号用例（仍缺）；`test_architecture_boundaries.py` 扫描范围已含 auth_service 改动（已通过）

## 7. 已知坑补充（新会话必读）

- **令牌段数歧义**：simple token 新格式（3 段 `ts.nonce.sig`）与 user token 旧格式（3 段 `ts.uid.sig`）段数相同——`auth_service.verify_user_token` 已用 try/except 兜底，但**任何新代码**在按段数分派令牌类型时需小心此重叠
- **并行子代理改同一测试文件**（本轮 test_lan_api.py 被组 A/D 同时修改）——复核子代理确认无覆盖，但下次并行修复时应明确拆分测试文件归属
- **并行时序误判**：组 B/D 曾把组 C 并行落盘的 domain/auth.py 改动误判为"预存改动"——跨组并行时，验证结果的归因要等全部落盘后再下结论
- 其余坑（Qt fill(0)、Windows 挂起诊断、RuntimeData 污染、bound 族测试停 worker、骨架测试补字段）沿用前序会话文档
