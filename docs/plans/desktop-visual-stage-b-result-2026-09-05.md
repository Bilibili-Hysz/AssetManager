# 桌面视觉统一 · 阶段 B 结果（基础控件规范收口）

> 状态：**STAGE RESULT（2026-09-05；已入库 commit 0db2ac5）**
> 依据：[阶段 A 草案](desktop-visual-stage-a-baseline-2026-09-05.md) §2/§3 + 主报告 V01/V02。
> 范围约束：本轮与并行 LAN 工作线互不接触（用户已约束并行子代理不碰 desktop 视觉面）。

## 1. 阶段 A 草案的实测修正

阶段 A 草案预估"98 处 QSS-px 待迁移"——本轮逐处核实后**修正**：98 处全部已是 token 派生式（startup `_font(key)`、themes `{f_sm}` 模板变量、stylekit `self.pt(size)px`），零违规。V01 的实际残余病灶是 **QFont 手写 pt 数字 12 处**。阶段 B 的工作量因此从"大迁移"收缩为"手写值接 token + V02 状态配方对齐"。

## 2. V01 收口：手写 pt → 语义 token（零视觉漂移）

**迁移 9 处**（token 值与原手写值逐点相等，渲染零变化）：

| 位置 | 原 → 新 |
|---|---|
| 网格名称 `_grid_widget.py:112` / `_grid_widget_data.py:82` | 9 → `font_size("xxs")` |
| 网格空态 `_grid_widget_render.py:155` | 11 → `font_size("caption")` |
| image_viewer 标题/加载/EXIF 标题/页脚/EXIF 正文 | 11/12/10/9/9 → caption/sm/xs/xxs/xxs |
| command_palette 输入框 `:270` | 14 → `font_size("lg")` |

**保持 3 处**：`_font_sub`/`_font_badge` 的 8pt——语义表最小 xxs=9，无 8 token；按阶段 A 草案"不机械替换数字"原则保持手写值，注释"grid density special case, stage C 校准"。

**棘轮数字**：`font-usage-inventory.json` 的 QFont 手写数字点 **12 → 3**；token 直通点 8 → 14。阶段 C 剩余工作即 3 处 8pt 特例（是否引入 xxs-2=8 或维持特例，待实机校准）。

## 3. V02 收口：状态配方对齐

1. **焦点边框统一 2px**：全局 `QLineEdit:focus` 族（themes.py:728）1px → 2px，对齐对话框工厂现状。按钮系（QPushButton 全局与工厂两侧本就同 1px）无分叉不动。
2. **禁用按钮单色源**：`StyleKit.button_css` disabled 分支由 `muted α0.25` 派生式 → `disabled_bg`/`disabled_text` token（对齐全局 themes.py:816 配方，带既有回退链）。
3. **只读分支判定不改**：read-only 与 disabled 是不同状态配方（header 背景 + muted 文字），全局 QSS 无对应规则、无分叉。

## 4. 验证锚点（阶段 A 基线的首次实战）

- **空库主窗截图的预期漂移**：`main_window_empty_navy` 摘要确定性红——像素取证（4830px，x853-1106/y750-769）定位到 InfoPanel 空态 Open/Copy Path 按钮的禁用态：旧 `rgba(muted,0.25)` 合成色 (53,58,71) → 新 `disabled_bg #12141e` + `disabled_text #4a5270`。**这是 V02 禁用态统一的直接视觉证据**（活体复现吻合），按 `SCREENSHOT_UPDATE=1` 再生并审查 diff——基线双轨机制的第一次预期内再生。
- StyleKit 快照：恰好 4 行变化（四个 variant 的 `QPushButton:disabled`），其余规则逐字不变。
- 其余 8 张截图摘要零变化（焦点边框 2px 不在截图状态覆盖内——验证了阶段 A "截图不涉输入框焦点态"的预判）。

## 5. 验证记录（2026-09-05，验证于入库前工作树）

- `pytest tests/desktop`（默认 xdist）→ **839 passed**；基线模块 `-n 0` → 13 passed（×多次）
- `pytest tests/unit tests/integration` → **2715 passed, 17 skipped**（基线持平；期间 `test_collection_service_publishes_collection_changed` 出现的 xdist flake 已在干净工作树复现 5/6 同红，实证为预存 EventBus 单例竞态，与本轮无关）
- 三样式门禁：`check_style_sources` 0 violations/94 files；`check_style_dialects` 0 legacy；`check_inline_styles` 232/39 基线持平
- ruff / pyright（全库 0 errors）绿
- 改动文件：themes.py、stylekit.py、command_palette.py、image_viewer.py、网格三文件、`test_font_metric_baseline_a.py`（证据断言 token 化）、清单 JSON、快照 TXT、空库 PNG+manifest

## 6. 阶段 B → C 衔接

| 事项 | 状态 |
|---|---|
| V01 手写 pt 收口 | 9/12 迁移，3 处 8pt 密度特例待阶段 C 校准 |
| V02 焦点/禁用对齐 | ✅ 本轮 |
| V03（分享设置按钮栏例外）、V06（零值与尺寸规则） | 阶段 C/D（主界面→弹窗族） |
| 主报告 §8 的 B 阶段完成条件"主题/缩放往返、各状态和三语通过" | 缩放/三语已由既有测试覆盖；焦点 2px 的几何断言建议阶段 C 补（截图状态矩阵扩展 focus 态） |

无证据即 unverified——本文档自身也是这个纪律的适用对象。
