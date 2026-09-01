# 会话启动文档 — PySide6 桌面端 UI/SVG 修复工作交接

> **使用方式 A（推荐）**：把本文件**全部内容**作为新会话的第一条消息。
> **使用方式 B**：新会话第一句话写：「先阅读 `docs/compose/reports/opencode-session-2026-08-10-startup.md` 和 `docs/compose/reports/opencode-session-2026-08-10-summary.md`，然后按启动文档的『下一步』执行。」
>
> 本文件是"快速启动包"，细节请查 `opencode-session-2026-08-10-summary.md`（17 章完整汇总）。

---

## 一、开场指令（可整段粘贴给新会话）

```
请作为本项目的工程代理，继续以下工作。

【项目】基于 Python PySide6 的桌面资产管理器（含 aiohttp LAN 分享服务），仓库位于
D:\~Vibe-Coding\Projects\AssetsManager_old-bak。分层：Presentation（window.py/panels/widgets/dialogs）
→ Controllers → Application（服务层）→ Domain → Infra（core/repositories）→ LAN（aiohttp，约 9.4k 行）。

【背景】此前的 Opencode 会话（ses_017505339ffeas793xTPQ7FLKL）已完成 11 轮工作：
UI/SVG 绘制 Bug 审计与修复（13 项）、图标 SVG 化迁移（含 fill(0)=不透明黑的根因修复）、
图标语义色体系（6 个 icon_* token，63 调用点迁移）、主题色响应修复、菜单栏审查（6 项）、
逐模块排 Bug（8 份清单约 177 项：高 15/中 41/低 121）、P0 高危修复轮（15+4 项全修）。
完整过程见 docs/compose/reports/opencode-session-2026-08-10-summary.md。
所有代码改动均在工作区【未提交】状态，与约 191 个预存修改文件混在一起。

【当前状态】中危修复轮（D1 LAN 认证路由 / D2 LAN 工具链 / E 文件操作撤销 / F 导出维护 /
G1 core 存储 / G2 runtime 身份，六组约 49 项）已全部落盘完成、审计通过，但【最终回归验证被中断】，
需先确认全量测试绿，再进入后续轮次。

【下一步，按优先级】
1. 中危轮收尾：按下方"验证命令"跑分片回归，修复任何残留失败；抽查 D1/D2/E 落盘完整性
2. 处理中危清单剩余项（docs/reports/module-*.md 中未修的项，如 lan-core 限流/令牌撤销）
3. P1 轮：M6a 资产服务 / M9 repositories SQL 安全 / M6c 分享与商业（配额竞态、订单状态机、金额精度）
4. P2 轮：M1 file_list / M2 info+sidebar / M3 dialogs（sharing_settings_dialog 2161 行）/ M4 窗口 dock / M5+M7（约 121 项低危）
5. 补测试缺口：tests/unit/test_tray.py 无 QApplication fixture 会挂起；grid 补 scale 重排/省略号用例

【红线】
- 不要 commit / push（仓库无远程 remote；工作区有用户预存未提交改动，git diff 中与任务无关的 hunk 勿动勿回退）
- 不要修改 DeepSeek Docs/ 目录
- 执行模式：探索排 Bug → 修复子代理（文件集互不相交）→ 第二子代理复核真实性 → 修复后审计子代理复审 → ruff + 定向 pytest 全绿
- 涉及 RuntimeData 扫描/迁移的脚本必须支持显式库根参数（目录会被测试残留严重污染）
- 探针脚本注意：QIcon.pixmap(n,n) 在图标实际尺寸小于 n 时返回实际尺寸，越界采样会得到错误像素
```

---

## 二、已完成工作速览（11 个阶段，一行一个）

| 阶段 | 内容 | 结果 |
|------|------|------|
| 1 | 第一轮 UI 绘制审计 | 13 项（5 确认 Bug + 8 次要），双子代理审计 13/13 确认 |
| 2 | 并行修复轮 | 11 文件 137+/27-，91 passed，审计 12/12 |
| 3 | 图标 SVG 化规划 | 黑底根因确认：`pixmap.fill(0)` = 不透明黑（Qt color0） |
| 4 | SVG 化执行 | 黑底修复（fill transparent）、toast SVG 化、sidebar emoji 收口、幂等迁移脚本 |
| 5 | RuntimeData 清空回归 + hover 核查 | 169 passed；hover 动画零改动（0.25ms 基准），卡顿源=RuntimeData 污染 |
| 6 | 主题色响应检查 | 颜色跟随 ✓；修 favorite/recent 对比度（10 浅色主题）、Default muted、菜单 QAction 图标刷新 |
| 7 | 图标语义色体系 | 6 个 icon_* token（JSON 可覆盖），63 调用点/21 文件迁移，160 passed |
| 8 | 菜单栏审查 | 6 项修复（选中项对比度 17/22 主题 <4.5 为最严重），审计 6/6 |
| 9 | 逐模块排 Bug | 8 代理 → 8 份清单约 177 项（高 15/中 41/低 121） |
| 10 | P0 高危修复轮 | 15 高 + 4 顺带全修；370 passed；LAN 513 + 桌面 547 无回归 |
| 11 | 中危修复轮（进行中） | 六组全部落盘 + 审计通过；**最终回归验证被中断** ← 从这里继续 |

---

## 三、当前工作区状态（最重要）

- **所有改动未提交**：会话全程零 commit；改动与约 191 个预存修改文件混合在工作区（git status 约 507 行）
- 最近 HEAD 提交是 webui 相关（与本桌面工作无关）
- 迁移脚本 `scripts/migrate_legacy_icons.py` 正常状态：`libraries scanned: 10, failed: 0`
- RuntimeData 已被用户清空过（测试残留 10.5 万目录已消失），再次跑测试后可能重新污染

---

## 四、文档索引（仓库内既有产物）

| 文件 | 内容 |
|------|------|
| `docs/reports/ui-rendering-audit-2026-08-10.md` | 13 项 UI Bug 审计 + 双子代理结论 + 修复记录 |
| `docs/plans/icon-svg-migration-2026-08-10.md` | SVG 化规划、黑底根因、主题色修复、语义色体系 |
| `docs/reports/menubar-review-2026-08-10.md` | 菜单栏 6 项修复 + 审计附录 |
| `docs/plans/bug-hunting-2026-08-10.md` | 逐模块排 Bug 计划 + P0 轮结果 + 高危修复记录 |
| `docs/reports/module-{lan-core,lan-routes,lan-tools,file-ops,maintenance,core-db,core-store,runtime}.md` | 8 份模块缺陷清单（含行号与修复建议）—— P1/P2 轮的直接工作输入 |
| `docs/compose/reports/opencode-session-2026-08-10-summary.md` | 17 章完整汇总（本文件的细节版） |

---

## 五、关键机制速查（新代理必读）

- **图标**：`core/icons.py` SVG 注册表 `icons.icon(name, color=None, size)`；color 三态：`None`→icon_primary、语义 token 名→themes.color() 解析、hex/rgba→原样（额外需求通道）；DPR 感知渲染；缓存键 `(name, tint, size, dpr)`；`icons.clear_cache()` 主题切换时调用
- **主题**：`core/themes.py` + `theme_loader.py` JSON 热重载；`Assets/Themes/` 22 个主题（D_ 深/L_ 浅/U_ 自定义）；文本 token（heading/body/muted/accent/on_accent/favorite/recent）+ 图标 token（icon_primary/icon_secondary/icon_muted/icon_on_accent/icon_accent/icon_disabled）+ 属性（hover_overlay/opacity 等）
- **RuntimeData**：库数据按哈希槽位存放；`Shared/<hash>.identity` 为库身份标记（`path_resolver.py`：root_identity/library_data_name/library_data_identity_path）；迁移脚本默认不扫描 RuntimeData
- **LAN**：aiohttp 服务器，认证 fail-closed（DB 异常拒绝放行）、缩略图/分享排除 .svg + nosniff、ZIP 拒绝 symlink 越界（阶段 10 已修）
- **文件操作**：move 禁止覆盖已存在目标；撤销删除恢复投影快照（tags/meta/favorites）；批量 move 部分成功的撤销记录缺失（file-ops #13，待扩展 FileOperationResult 契约）

---

## 六、验证命令速查

```powershell
# 静态检查
python -m ruff check AssetsManager/

# 中危轮相关回归（会话中断处，先跑这个确认全绿）
python -m pytest tests/core tests/unit -k "settings or cache or tag_library or json_store or config_migrator or project_data or file_operation or undo or integrity or maintenance or export or runtime or reconciliation or crash or security_preflight or tool_scheduler"

# 定向核心（UI/图标层）
python -m pytest tests/core/test_icons.py tests/core/test_themes.py tests/core/test_bg_effects.py tests/unit/test_workspace_bar.py tests/desktop/test_file_list_grid_widget.py -q

# LAN 全量（约 513 项，慢）
python -m pytest tests/lan -q

# 全量（基线 2790 passed, 7 skipped；耗时较长）
python -m pytest tests -q
```

---

## 七、已知坑清单

- `QPixmap.fill(0)` 是不透明黑（`Qt.GlobalColor.color0`）—— 透明必须写 `fill(Qt.GlobalColor.transparent)`
- LSP 报错 `_grid_widget.py:1060` 附近 "data/index is not a known attribute of None" 为既有 stub 噪音，非本次引入
- 测试文件路径易错：`test_workspace_bar.py` 在 `tests/unit/`（非 desktop）；`test_tag_service.py` 在 `tests/integration/`；`test_startup.py` 实际是 `test_startup_window.py`；`test_color_utils.py` 不存在
- `tests/unit/test_tray.py` 缺 QApplication fixture 会挂起（预存问题）
- Windows 环境：目录 symlink 测试无权限会 skip；进程终止类测试不具确定性会 skip（均为预期）
- 主题切换后图标刷新链路：`theme_changed` → `icons.clear_cache()` + `_refresh_ui_icons`（coordinator，含 `_refresh_tools_menu_icons`）→ 各面板重建
- 图标语义色迁移后遗留扫描：`color=themes.get()[...]` / `t[...]` 硬编码调用点应为 0
