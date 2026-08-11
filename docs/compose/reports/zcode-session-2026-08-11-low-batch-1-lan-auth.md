# ZCode 会话汇总 — P2 低危首批（LAN 认证面 lan-core Bug 14-21，2026-08-11）

> **来源会话**：ZCode（deepseek-v4-flash），2026-08-11
> **任务来源**：P2 轮交接的下一步（低危清单 ~80 项的首批：LAN 认证面）
> **性质**：全程未 commit；改动与预存 WIP 混合在工作区
> **验证基线**：全量 `pytest tests -q` → **3019 passed, 7 skipped, 0 failed**（净增 36 测试，与基线 2983 吻合）

## 1. 完成内容

**8 项审计问题**（4 个并行修复组 + 主代理）：

| 组 | 文件 | 修复项 |
|---|---|---|
| A | `routes/auth.py`、`application/auth_service.py`、`routes/system.py` | **Bug 15** 空登录 400（原 200 {"ok": True}）；**Bug 16** 登录三分支统一 "Invalid username or password"、重复注册 "Registration failed"；**Bug 17** /api/info 有意公开面文档化（零行为变更）；Bug 21 调用点 ×4（secure=lan.ssl_active） |
| B | `lan/security.py`、`lan/server.py` | **Bug 14** `_normalize_ip`（IPv4-mapped/::1 归一化）+ `tunnel_active` 隧道回环放行 + `_tunnel_active` 接线；**Bug 20** server 侧 `_shutdown` 停扫描 |
| C | `routes/_helpers.py`、`routes/shares.py`、`lan/scanner.py` | **Bug 21** `set_auth_cookie`/`set_share_cookie` 加 keyword-only `secure=False`（调用点 `request.app.get(LAN_APP_KEY)` 防御取 ssl_active）；**Bug 20** scanner 侧 `stop()`（取消标志 + join(2s) + walk 检查） |
| D | `lan/principal.py` | **Bug 18** viewer/未知角色 → viewer_caps（无 download，防绕过 guest 下载限制）；**Bug 19** `_as_int`/`_as_float` 安全默认值 |

**审计后追加修复**（审计子代理发现）：
- `seller_auth.py` `_set_seller_cookie` 补 Secure（`request.secure`，Bug 21 同族）
- `IPBlacklist.load_from_settings` 条目归一化（IPv6 文本形式黑名单条目不命中的不对称）

**测试**：4 个新文件（test_low_batch_auth/security/cookies_scanner/principal，36 用例）+ `test_lan_api.py` `_FakeLan` 补 `ssl_active=False`（1 行）+ 黑名单归一化 2 用例。

## 2. 关键问题与决策

- **Bug 17 保持公开（文档化决策）**：`/api/info` 的 auth_mode/share_name/library_stats 是前端登录页（LoginPage 按 auth_mode 渲染表单）与落地页（LandingPage 渲染统计）的**未认证依赖**，改为"仅认证可见"会破坏登录 UX。按项目惯例（限流 NAT 权衡同模式）以 NOTE 注释 + 报告标记处理，行为不变。
- **Bug 18 落地方式**：users 表 role 默认 'viewer' 且代码库唯一建用户路径 register_user 不指定 role → 所有自注册用户（含邀请码路径）均为 viewer。修复改为 principal 映射三分支（admin/user/其它→viewer_caps），而非"默认要求邀请码"（会破坏首用户引导与 10+ 既有测试）。
- **子代理事故 ×2**：组C 空返回失败（diff 全为预存 hunk，零有效改动）→ 主代理亲自实现；组B stash 事故（声称 pop 误弹 stash，经 refs/stash reflog 核实两 stash 完好无损、.gitignore 无冲突标记，描述夸大但无实质影响）。
- **协作契约**：跨组 API 契约（set_auth_cookie secure 签名、scanner.stop()、tunnel_active 回调）由主代理预先锁定，并行组按契约实现；`_FakeLan` 缺 `ssl_active` 的 fixture 缺口由主代理补一行解决。

## 3. 后续建议

- 低危清单下一批：**LAN 路径面**（lan-core Bug 8 NUL、Bug 9 NTFS ADS、lan-routes 8/9/10/11/13/14/15）或 **lan-tools**（scanner S2-S8、tunnel T5-T7、ws W5-W8、dto D3-D6）
- 残余（审计记录，均低危不阻塞）：Bug 16 的 PBKDF2 时序差（不存在/停用用户跳过哈希）；`get_user_permissions("viewer")` 与 viewer_caps 在 `lan_guest_download=True` 时的潜伏差异（该函数生产无调用方）
- 可选：性能轮（M6a-8 get_home 全表扫描、thumbnail index）或 DB migration v24
