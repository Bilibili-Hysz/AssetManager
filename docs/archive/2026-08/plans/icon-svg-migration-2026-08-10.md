# 界面图标 SVG 化推进规划（2026-08-10）

> 目标：消除桌面前端 emoji 图标与 SVG 图标并存现象，修复 SVG 图标纯黑背景，
> 建立统一的语义 SVG 图标体系。
> 状态：**规划待批准**（根因已实证，见下）。

## 一、现状侦察结论（已实证）

### 1.1 代码层：图标已 100% SVG 化

全部 UI 图标（按钮/菜单/树/对话框/状态指示，63+ 调用点）均走
`core/icons.py: icon()`（SVG path 注册表 + QSvgRenderer 渲染）。
代码中**无 emoji 字面量**（扫描确认，仅 `sidebar.py` 的 legacy 映射表含转义 emoji）。

### 1.2 根因：SVG 图标渲染在纯黑不透明底上（用户报告的直接根因）

**探针实证**（offscreen，PySide6）：

```
QColor(0)      -> #000000 alpha=255   （Qt.GlobalColor.color0 = 不透明黑）
pixmap.fill(0) -> #000000 alpha=255   （icons.py:117 当前行为）
pixmap.fill(QColor(0,0,0,0)) -> alpha=0（正确透明）

icons.icon("folder", '#ffffff', 16px) 渲染探针：
  opaque_black=173, transparent=0, colored=83   ← 无任何透明像素！
```

- 根因：`icons.py:117` `pixmap.fill(0)` —— 整数 `0` 被 Qt 解析为
  `Qt.GlobalColor.color0`（不透明黑），而非透明。
- 影响：**全部 SVG 图标带纯黑矩形底**。深色主题下面板同为深色，黑底隐蔽；
  浅色主题/半透明面板/背景图开启时黑方块极其突兀（用户所见"SVG背景纯黑"）。
- 注：此前两轮审计（2026-08-10 报告）均误判 `fill(0)` 为透明填充，此为其间遗留的
  深层缺陷，本次由实机观察 + 渲染探针实证。
- 正确写法对比（仓库内既有正确范例）：`tray.py:61` `fill(QColor(0,0,0,0))`、
  `_grid_widget.py:1055` `fill(Qt.GlobalColor.transparent)`。

### 1.3 emoji 残留点（仅数据层）

| 位置 | 数据 | 现状 |
|------|------|------|
| `favorites.json` 的 `icon` 字段 | 旧版直接存 emoji 字符 | `sidebar.py:41-52 _FAVORITE_ICON_MAP` 读取时映射 10 条（4 条已语义修正），其余 fallback "star" |
| `tag_metadata` 表 `icon` 字段（v3 迁移） | 可存任意字符串（含 emoji） | **UI 未渲染**（tag_tree 固定 "tag" 图标），死字段 |
| `Toast.icon` 参数（toast.py:68-74） | 任意文本 | 当前无调用点传 emoji，但 API 无校验 |
| 插件 descriptor `icon` 字段（host_context.py:145） | 字符串 | `window.py:240` 经 `icons.icon(..., fallback="wrench")` 渲染 |
| 写入点 `sidebar_favorites.set_icon`（:92） | 入参未规范化 | 右键菜单仅提供 ICONS 6 个 SVG 名，新写入安全 |

## 二、任务分解

### 阶段 0：修复黑底根因（最高优先级）

| 任务 | 文件 | 内容 |
|------|------|------|
| T0.1 | `core/icons.py:117` | `pixmap.fill(0)` → `pixmap.fill(Qt.GlobalColor.transparent)`（补 Qt import） |
| T0.2 | `tests/core/test_icons.py` | 新增回归断言：`icon()` 渲染 pixmap 存在透明像素（alpha==0），防黑底回归；同时断言线条像素存在（非全空） |
| T0.3 | 全仓库 | 扫描其余 `fill(<int>)` 误用（当前确认仅 icons.py 一处） |

### 阶段 1：emoji → SVG 收口（数据层规范化）

| 任务 | 文件 | 内容 |
|------|------|------|
| T1.1 | `dialogs/sidebar_favorites.py:92` | `set_icon` 写入前 `icons.normalize()` 规范化（存语义名，杜绝 emoji 再入库） |
| T1.2 | `application/tag_service.py:299-308` | `update_tag_metadata(icon=...)` 写入前规范化（拒绝 emoji） |
| T1.3 | `panels/sidebar.py:41-52` | `_FAVORITE_ICON_MAP` 扩充常见 legacy emoji：📷→image、⚙️→settings、🗑→trash、🔍→search、📄→file、💡→star 等（10→~18 条），降低 fallback 丢失率 |
| T1.4 | `repositories/tag_repository.py` / `tag_tree.py` | 决策 tag `icon` 字段：启用渲染（tag_tree 读字段→`icons.icon`）或标记归档不渲染。**建议启用**（字段已存在，启用即完成数据层 emoji 消费闭环） |
| T1.5 | `widgets/toast.py:68-74` | `icon` 参数进入时 `icons.normalize()` 校验（未知值 fallback），杜绝未来调用点误传 emoji |
| T1.6 | 迁移脚本（scripts/ 或启动钩子） | 一次性迁移：扫描各库 favorites.json 与 tag_metadata 中 emoji icon 值→SVG 语义名写回（幂等、可重复） |

### 阶段 2：图标词汇表扩充（增强，供 legacy 精确迁移）

| 任务 | 文件 | 内容 |
|------|------|------|
| T2.1 | `core/icons.py` `_ICON_PATHS` | 新增 24x24 线条风格 path：monitor、save、heart、info、external_link、play、pause、upload、download、folder_open（风格与现有一致，stroke 由渲染器注入） |
| T2.2 | `panels/sidebar.py:32` | `ICONS` 选择列表 6→~14 个（含新增），favorites 右键菜单更丰富 |
| T2.3 | `panels/sidebar.py:41-52` | legacy 映射升级为精确语义：💾→save、🖥→monitor（替换近似映射 file/grid） |

### 阶段 3：验证与收尾

| 任务 | 内容 |
|------|------|
| T3.1 | 渲染探针脚本（`scripts/` 或 tests 辅助）：全图标名 × 尺寸 {16,32,48} × 深浅主题色，断言无黑底（存在透明像素）、非全空（存在内容像素） |
| T3.2 | `ruff check` 全部改动文件 + 定向 pytest（test_icons、test_bg_effects、test_workspace_bar、test_grid、test_sidebar*、test_tray） |
| T3.3 | 文档：更新 `docs/reports/ui-rendering-audit-2026-08-10.md`（补记 fill(0) 根因与修复）、新增图标词汇表（语义名→SVG path→用途） |

## 三、执行顺序与并行委派方案

```
T0（icons.py 单文件，先做）
   └─> T1.1-T1.6（数据层，多文件，可并行组）
          └─> T2（icons.py + sidebar.py，与 T0/T1 串行，避免文件冲突）
                 └─> T3（验证）+ 独立审计子代理复审
```

- 修复子代理分组（文件集互不相交）：
  - 组 A：T0 + T3.1 探针（icons.py、test_icons.py、scripts/）
  - 组 B：T1（sidebar.py、sidebar_favorites.py、tag_service.py、tag_repository.py、tag_tree.py、toast.py、迁移脚本）
  - 组 C：T2（icons.py 词汇扩充 + sidebar.py ICONS）——待组 A/B 完成
- 审计子代理：全部完成后 2 组复审（渲染正确性 / 数据规范化与回归）

## 四、验收标准

1. `icons.icon()` 输出 pixmap 存在透明像素、无纯黑矩形底（测试锁定）
2. 代码与用户数据中不再产生新的 emoji 图标值（写入点规范化）
3. 旧数据（favorites/tag_metadata 含 emoji）读取/迁移后全部显示为 SVG 图标
4. 所有主题（浅色/深色/自定义）下图标视觉正常
5. 既有 91 项相关测试 + 新增测试全部通过；ruff 通过

## 五、风险与边界

- **视觉变更**：黑底消除后图标在浅色主题/背景图下的呈现与之前不同——属预期修复；
  需人工目检 1-2 个主题确认。
- **系统托盘/任务栏**：`assets/icons/icon.ico` 位图不受影响（不经过 icons.py）。
- **webui**（React）图标体系独立，不在本任务范围。
- **插件兼容**：插件 descriptor 的 icon 若为 emoji，T1.5 的 normalize 兜底保证
  fallback 显示（不崩溃）；`_ALIASES` 死代码（Bug 9）保持不动以免破坏插件容错。
- **迁移幂等**：迁移脚本必须幂等且失败安全（单库失败不影响其他库）。

---

## 六、主题色响应检查与修复（2026-08-10 续）

### 检查结论（探针实证）

- **颜色跟随**：63 个 `icons.icon()` 调用点全部使用主题 token（默认 tint = `heading`）；图标随 `theme_changed` → `icons.clear_cache()` + 各面板刷新即时重建（端到端探针：Navy #e8ecf8 → Dawn #241c10 → Dracula #f8f8f2，渲染线条色与 tint 完全一致）。
- **深浅方向**：深色主题图标浅线、浅色主题图标深线，方向正确，无"深色时变浅/浅色时变深"反转。

### 发现并修复的 3 个问题

1. **浅色主题 favorite 图标偏淡（10 个主题）**：favorite `#b89020` 在浅色面板上对比度仅 2.71-2.83（<3.0，收藏节点头图标不可辨）。→ 10 个浅色主题 JSON 改 `#6b5216`（对比 6.7-7.0）；recent `#5a90b8`→`#35637f`（3.1→5.9-6.2）。
2. **Default 主题 muted 对比不足**：`#666666` vs panel `#252525` = 2.67。→ `#757575`（≈3.3）。影响 Default 下 info 面板/空状态等 muted 图标。
3. **菜单栏 QAction 图标不随主题刷新**：`window.py` 工具菜单 action 图标创建时一次性 setIcon，主题切换后旧色图标残留在新背景上（深→浅切换时浅色图标在浅色菜单上不可见）。→ `_setup_tools_menu` 保存 `(action, icon_name, fallback)` 规格，新增 `_refresh_tools_menu_icons()`，由 `WindowCoordinator._apply_theme` 经 `_refresh_ui_icons` 调用。

### 验证

- `ruff check` 通过；pytest 77 passed（icons + grid）
- 对比度全量复核：22 主题 × heading/body/muted/accent/favorite/recent/on_accent vs panel/base，**LOW 组合 0**
- 主题切换端到端探针：Navy→Dawn→Dracula 渲染线条色与主题 heading 一致，缓存重建正确

---

## 七、图标语义色体系（2026-08-10 续）

### 动机

此前图标颜色虽非硬编码（调用点取主题 token 的 hex），但语义分散：17 处取 heading、12 处取 body、8 处取 muted，散落 20+ 文件且同类别控件 token 不一，主题无法统一调控图标色。

### 改造内容

1. **主题系统**（`core/themes.py` `_EXTENDED_FALLBACKS`）：新增 6 个图标语义 token，默认继承文本 token，主题 JSON 可覆盖：
   | token | 默认继承 | 用途 |
   |-------|---------|------|
   | icon_primary | heading | 菜单/工具栏/标题栏/强调按钮 |
   | icon_secondary | body | 树节点/列表/普通按钮 |
   | icon_muted | muted | 辅助按钮/关闭/占位 |
   | icon_on_accent | on_accent | 强调背景上的图标 |
   | icon_accent | accent | 强调色图标 |
   | icon_disabled | disabled_text | 禁用视觉 |

2. **icons.py**：`icon()` 的 `color` 参数三态输入：
   - `None` → 自动取 `icon_primary`
   - 语义 token 名（`_SEMANTIC_COLORS` 集合，含全部现有 token + icon_*）→ `themes.color()` 解析
   - 显式颜色字符串（hex/rgb/rgba）→ 原样使用（额外需求通道）

3. **63 个调用点迁移**（3 个子代理、21 个文件）：`t["heading"]`→`"icon_primary"`、`t["body"]`→`"icon_secondary"`、`t["muted"]`→`"icon_muted"`、`t["on_accent"]`→`"icon_on_accent"`；sidebar favorite/recent 分派改为 `"favorite"`/`"recent"`。渲染结果与迁移前逐像素一致（默认值 = 旧 hex）。

4. **保留的动态多态色**（额外需求通道，显式 hex/动态分派仍受支持）：
   - status_indicator 状态色（accent/success/danger/warning）
   - tag_editor / tabbed_dialog 按钮多态色
   - toast level 色、image_viewer hover 动态色
   - badge 分类固定色（CATEGORY_BADGE_COLORS）、video 紫 #c480d4

### 验证

- ruff 全绿；160 passed（icons 9 含语义色解析 4 项新测试、tag_chip、grid、sidebar、tag、toast 等）
- 遗留扫描：`color=themes.get()[...]` / `t[...]` 硬编码调用点 = 0
- 主题跟随探针：Navy→Dawn→Dracula 渲染不变
- **覆盖能力实证**：临时主题 JSON 覆盖 `icon_primary=#ff00ff` → 默认图标全局渲染 (255,0,255)，一键统一图标色
