# 性能审查 W6 · Windows 包冒烟（2026-09-07，PF-5 修后更新）

> **修订 4：** 下文保存 `68ab0e4` 候选包的历史功能冒烟。第四轮复核指出最大化种子不等于窗口实态、结束超时不等于托盘、缺少正常退出—重开证据。本轮已强化探针并重新构建；当前候选和验收范围统一见 [收口与交接报告](../week-closeout-2026-09-08.md)。不要将历史“四变体可交付”用于本轮未提交修复后的包。

> 状态：**frozen 包可交付 — 候选包哈希绑定干净（工作树零脏文件）+ 包内功能验收完成（2026-09-08 第三次修订）**
> 环境：PyInstaller 6.19.0 / PySide6 6.11.0 / Python 3.14.3
>
> **修订 3（2026-09-08，第三轮复核 F5 后）**：F1/F2 生产修复（`68ab0e4`）之后，按
> "候选包必须绑定其自身源码"的要求**重建双模式包并重跑全部四变体包内功能验收**
> （新增备注评分取证项，四变体全过）。[哈希清单](evidence/w6-package-hash-manifest.json)
> 绑定 HEAD `68ab0e4` 且**工作树零脏文件**——包内容与提交源码严格一一对应。
> 证据：[onefile](evidence/w6-functional/onefile.json) ·
> [onefile-maximized](evidence/w6-functional/onefile-maximized.json) ·
> [onedir](evidence/w6-functional/onedir.json) ·
> [onedir-maximized](evidence/w6-functional/onedir-maximized.json)（各含日志 .txt）。
>
> **修订 2（2026-09-08）**：R5 降级时登记的两项缺口已全部补齐——
> ① 哈希绑定 + ② 包内功能验收（四变体 PASS）。第一次修订时"启动冒烟通过、功能验收待补"
> 的降级状态自本修订起解除。
>
> **修订 1（2026-09-08 复核处置 R5）**：本报告曾以"ALL PASS — 4 frozen 模式全部可交付"作结，
> 独立复核指出该结论缺乏哈希绑定与包内功能证据，据此降级为"启动冒烟通过、功能验收待补"。

## 1. 构建（2026-09-08 重建 ×2，哈希绑定候选包）

| 模式 | 结果 | check_package_contents |
|---|---|---|
| onefile (`dist/AssetManager.exe`, 59.6 MB) | ✅ 构建成功 | ✅ verified |
| onedir (`dist/AssetManager/`, 139.0 MB) | ✅ 构建成功 | ✅ verified |

WebUI dist：从当前源码重建（vite build ✓，产物哈希入清单）。

## 2. 包内功能验收（2026-09-08，四变体全 PASS ×2 轮：初始包 + F1/F2 后候选包，均含备注评分项）

驱动方式：探针种子化隔离运行域（`AM_RUNTIME_ROOT` + 合成库 12 PNG + 共享自启设置），
启动真实 frozen 二进制，操作者经真实 StartupWindow 一键开库，随后探针自动取证：

| 检查 | onefile | onedir | 证明内容 |
|---|---|---|---|
| `/api/info` 200（share_name/auth 正确） | ✅ | ✅ | 库已打开 + LAN 自启 + 会话绑定（含 PF-2 aiohttp 首次延迟依赖在包内生效） |
| 密码登录签发 lan_token | ✅ | ✅ | 鉴权合同 |
| `/fonts/inter-var-latin.woff2` 与 webui/dist 逐字节一致（48256 B） | ✅ | ✅ | SPA 字体资产 |
| 单图缩略图可解码（WEBP 178 B，内容协商） | ✅ | ✅ | 缩略图管线 |
| 批量缩略图 12/12 | ✅ | ✅ | 批量合同 |
| 运行中新增文件出现在 `/api/files` | ✅ | ✅ | 实时变化 |
| maximized=true 持久化被消费且进程存活（PF-5 场景） | ✅ | ✅ | 延迟最大化修复在 frozen 包内有效 |
| WM_CLOSE 语义 | 隐藏到托盘（托盘存在时的正确语义）；强制结束码 1 | 同左 | PF-6 归因数据（见 §5） |

证据：[onefile](evidence/w6-functional/onefile.json) ·
[onefile-maximized](evidence/w6-functional/onefile-maximized.json) ·
[onedir](evidence/w6-functional/onedir.json) ·
[onedir-maximized](evidence/w6-functional/onedir-maximized.json)（各含对应日志）。

## 3. PF-5 根因与修复（历史记录）

**根因**：`_restore_window_geometry` 在 `__init__` 期间调用 `showMaximized()`（line 156），此时
`_setup_ui()` 尚未执行——widget tree（dock/central/layout）不存在。`showMaximized()` 触发原生
resize+show 事件，C 侧分发进入不完整的 widget tree，frozen 引导阶段 Python 处理器不可达 → 原生
段错误。开发模式下同一操作产生 Python 级异常（可捕获但不稳定，即 PF-1 变体）。

**修复**：`showMaximized()` 延迟到 `_setup_ui()` 完成后——`_restore_window_geometry` 改为存
`setattr(window, "_pending_maximized", flag)`，`__init__` 在 `_setup_ui()` 返回后检查标志并调用
`showMaximized()`。本次包内验收第 7 项即该修复的 frozen 实证。

## 4. 验证矩阵（2026-09-08 终态）

| frozen 模式 | 修前（09-07） | 09-07 启动冒烟 | 09-08 包内功能 |
|---|---|---|---|
| onefile normal | ✅ | ✅ ALIVE 8s | ✅ 全项 PASS |
| onefile maximized | ❌ segfault | ✅ ALIVE 8s | ✅ 全项 PASS |
| onedir normal | ❌ segfault | ✅ ALIVE 8s | ✅ 全项 PASS |
| onedir maximized | ❌ segfault | ✅ ALIVE 8s | ✅ 全项 PASS |

## 5. 登记项

| # | 级别 | 内容 | 状态 |
|---|---|---|---|
| ~~PF-5~~ | ~~P1 阻断~~ | ~~frozen maximized 段错误~~ | ✅ 已修 + 包内实证（d11ad45；0937a95 后重建复验） |
| PF-6 | P3 | **归因更新（09-08）**：WM_CLOSE 在托盘可用时的应用语义是隐藏到托盘而非退出；随后的强制结束退出码为 1。"exit code=1"不再解释为异常退出路径，而是"托盘常驻 + 强制终止"的组合结果。仍待办：为无托盘/纯 WM_CLOSE 退出路径归因退出码 | 归因部分完成 |

## 6. 交付结论（2026-09-08 第三次修订）

**候选包（HEAD `68ab0e4`，工作树零脏文件）四变体全部通过包内功能验收，frozen 包可交付。**
包内验收覆盖：开库/共享自启/LAN 字体逐字节/缩略图/备注评分写读/实时变化/PF-5 最大化消费/
关闭语义。保留说明：真机长时使用与视觉走查（Stage F 十六步）仍属用户真机验收范畴。

无证据即 unverified——本文档自身也是这个纪律的适用对象。
