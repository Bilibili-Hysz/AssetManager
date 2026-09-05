# 桌面视觉统一 · 阶段 A 基线与规范草案

> 状态：**STAGE RESULT（阶段 A 交付记录，2026-09-05）**
> 依据：[desktop-visual-consistency-2026-09-05.md](../reports/desktop-visual-consistency-2026-09-05.md) §8 阶段 A + §9 验收矩阵 + V01/V02。
> 本文档记录阶段 A 的三个交付物（固定样本、截图基线、字体度量对照）与两项规范草案（文字角色单位、控件状态规则）。**草案 = 待阶段 B 校准的决定建议，未实施。**

## 1. 交付物清单（全部已落地并可重复运行）

| 交付物 | 载体 | 验证命令 |
|---|---|---|
| 固定样本库 fixture builder（A-1） | `tests/desktop/visual_conftest_helpers.py`（`build_sample_library`，3 profile：empty/minimal/representative；字节内容写死 + mtime 钉死 epoch + 真实 TagService 打标；确定性已实证：双次构造 metadata 全等） | 随下两项 |
| 截图基线双轨（A-2，本仓**首例整窗 MainWindow 实例化**） | `tests/desktop/test_visual_baseline_a.py`（9 用例：主窗 idle×2 主题/空库/网格×2/详情/Info 聚焦/ThemePreview 模态/启动窗）+ PNG 证据 `evidence/screenshots/`（9 张 + manifest.json 全 §9.3 元数据）+ 摘要棘轮 `tests/desktop/snapshots/visual_baseline_digests.txt` | 单模块 `-n 0`：9 passed；再生 `SCREENSHOT_UPDATE=1` |
| 字体度量对照（A-3，V01 机器可读证据） | `tests/desktop/test_font_metric_baseline_a.py`（4 用例）+ `evidence/font-usage-inventory.json`（三族清单 98+19+1）+ `evidence/font-caption-metrics.json`（pt/px 度量对照）+ 清单防漂移棘轮（`FONT_INVENTORY_UPDATE=1` 再生） | 单模块 `-n 0`：4 passed |

截图矩阵（克制覆盖，不做笛卡尔积）：Navy（暗代表）+ Dawn（亮代表）；representative profile（长名/多标签/渐变彩图/子目录）；状态覆盖 idle + hover + 选中。

### 阶段 A 实施中发现的生产代码问题（登记给阶段 B/C，未修）

1. **MainWindow 构造时序缺陷**（window.py:175 `_restore_window_geometry` 先于 :182 `_bg_resize_timer`/`:177 _bg_cache` 初始化）：持久化 `window_maximized=True` 或带几何 settings 下，构造期 resizeEvent 触达未初始化字段 → AttributeError → C++ 段错误。真机用户命中即崩（真机 settings 恰好为空才没炸）。测试侧已内存清键绕过；**根治需生产修复**。
2. **ShortcutManager 生命周期缺口**（window.py:612-640 注册后不 unregister）：同进程第二个 MainWindow（app.py:230 重开路径）时 `register_action` 触已删 QAction → shiboken 崩溃。
3. **WorkspaceSection 指示器动画未接 reduce_motion**（workspace_bar.py:54，200ms QPropertyAnimation）：违反 V07 统一减弱动态效果契约；也是截图确定性的对抗源。
4. **TabbedDialog 关闭路径整字典落盘**：几何持久化伴随 `settings.save()` 把整个内存字典写盘（recent_libraries 等无关键被顺带持久化）——跨用例状态污染放大器。
5. **网格 16ms 定时器进度按回调次数推进**（动画文档 §2 已确认）：界面忙碌时完成时间伸长——M0 时间驱动模型的直接输入。

### 机器环境导致的测试侧修复（本阶段完成）

本机持久化 `reduce_motion=True` 与 `ui_scale=0.9` 会污染读取 AppSettings 的测试（阶段 A 摸底即预警此风险模式）：
- 网格纹理保留 ×2 + tab_container 面板动画 ×1：测试侧钉 `widget._animator._reduce_motion = False`（同文件 `test_grid_enter_respects_reduce_motion` 的既有模式），修后串行/隔离全绿。
- 截图基线全部用例已在 fixture 内钉 ui_scale=1.0（内存级 set，不写盘）。

### 已知限制：截图摘要棘轮的进程隔离运行约定

共享进程串行全套（`pytest tests/desktop -n 0`）下，前序测试的进程级渲染残留会干扰逐行哈希——已实证 `test_settings_dialog` 语言往返后，滚动条 track 的透明背景在 offscreen 下解析为 (0,0,0) 而非主题 base 色。用例单独跑或默认 xdist（worker 独立进程）全绿。**约定**：验证截图摘要用"单模块 -n 0"或"全套默认 -n auto"，不用 `-n 0` 跑整套；详见 `test_visual_baseline_a.py` 模块 docstring。

## 2. 规范草案一：文字角色单位（V01 治理方案，待阶段 B 校准）

### 现状证据（font-usage-inventory.json，2026-09-05）

| 管线 | 处数 | 形态 |
|---|---|---|
| QSS `font-size:…px` | **98 处 / 20 文件** | startup.py 26、theme_preview.py 11、stylekit.py 8、info.py 8…… |
| QFont.setPointSize（全 pt） | **19 处 / 7 文件** | command_palette 6（语义 token→pt）、image_viewer 5、网格手写 9/8/11 pt 6 处、app/window 基准字体 2 |
| QFont.setPixelSize | **1 处** | tray.py:73（托盘图标内嵌数字） |

实测（font-caption-metrics.json）：同一 `caption` token=11，pt 构造 height 15px vs px 构造 height 11px——**单位不同 → 度量不同**，V01 的渲染级证据。

### 草案决定建议（阶段 B 校准后实施）

1. **规范单位 = pt（经 `scaled_pt`）**。理由：Qt 语义字号的事实单位（本仓 `themes.font_size()` 返回的就是磅值）；QFont/自绘两管线都消费；跨 DPI 由 Qt 字体机制处理。px 族不是"错"，是"绕过了主题字号角色"——98 处 QSS px 的病灶在于**数值不经 `scaled_px( themes.font_size(role) )` 派生**，不在 px 单位本身。
2. **两个适配入口**（报告 V01 任务原文的落地形态）：
   - QSS 侧：StyleKit 工厂与 themes.stylesheet() 输出的 font-size 一律 `font-size: {scaled_px(themes.font_size(role))}px`——**QSS 只有 px 语法**，所以"单位规范"在 QSS 侧的含义是"数值必须从 token 派生"，不是字面换 pt；
   - QFont/自绘侧：`QFont.setPointSize(scaled_pt(themes.font_size(role)))`。
   两侧从同一 token 派生 → 同角色度量等效（这正是双入口的验收标准）。
3. **迁移次序**（先共享规则再迁移调用方，阶段 A→B 衔接）：token→工厂（stylekit.py 8 处）→ 高频手写点（startup.py 26、theme_preview.py 11）→ 网格自绘 6 处手写 pt → command_palette/image_viewer token 直通点。**不机械替换数字**：手写 9/8 先映射到最近语义角色（xs=9 / xxs=8），数值差异在校准样板阶段裁决。
4. **棘轮已就位**：`test_font_usage_inventory_matches_evidence` 比对扫描 vs 落档清单——任何新增/删除 `setPointSize|setPixelSize|font-size:…px` 都会红，`FONT_INVENTORY_UPDATE=1` 再生 + 提交说明写理由。阶段 B 迁移时这个棘轮就是进度表（数字只降不升）。
5. **豁免登记**（预计）：tray.py:73 setPixelSize（托盘位图内嵌数字，px 合理）；抗锯齿/渲染提示类代码不算字体角色。

## 3. 规范草案二：控件状态样式规则（V02 治理方案，待阶段 B 校准）

### 现状证据（报告 V02 + 截图基线可复核）

- 全局输入框焦点边框 themes.py:728 = 1px；对话框工厂 stylekit.py:247 = 2px——同语义不同强度。
- 禁用按钮：全局用 `disabled_bg/disabled_text`（themes.py:816）；StyleKit.button_css 用 muted 透明派生（stylekit.py:449）——同状态两套色源。
- 滚动条：全局 QSS / 对话框工厂 / 自绘视图三处各自定义。

### 草案决定建议

1. **状态配方集中**：idle/hover/pressed/focus/disabled/selected/read-only 每状态一个具名配方（token 组合 + 边框宽 + 圆角沿用），落在 themes.py 或 stylekit.py 单点；全局 stylesheet() 与各工厂都引用它——保留具名变体（紧凑/标准）作为一级概念。
2. **焦点边框**：统一 2px（对话框工厂现状为准，全局 1px 收紧）；焦点不改变控件几何（无跳动）。
3. **禁用态**：统一 `disabled_bg/disabled_text` token（StyleKit 派生式废弃或并入 token）。
4. **验收锚点**：阶段 A 截图基线即对照页——同一主题下主界面/设置/分享设置的 idle/hover/focus/pressed/disabled 截图，只有明示变体允许不同（报告 V02 验收原文）。阶段 B 每迁移一个状态配方，`SCREENSHOT_UPDATE=1` 重生成前后对照。

## 4. 阶段 A → B 衔接清单

| 事项 | 状态 |
|---|---|
| 固定样本 + 截图基线 + 字体清单 | ✅ 已落地（本文档 §1） |
| 文字角色单位规范草案 | ✅ 本文 §2，**待阶段 B 样板校准**（2-3 个代表组件：startup 卡片标题 / 网格名称 / 设置页正文） |
| 状态样式规则草案 | ✅ 本文 §3，**待阶段 B 焦点边框几何断言 + 三域对照截图** |
| 生产代码修复（构造时序/快捷键生命周期/指示器 reduce_motion） | 登记 §1 待排期（构造时序缺陷建议优先——真机崩溃路径） |
| 动画 M0（时间驱动模型）衔接 | 动画文档 §2 已确认网格定时器问题为 M0 直接输入；A 阶段样板页（截图矩阵）即 M1 样板的静态对照基线 |

## 5. 阶段 A 验证记录（2026-09-05，验证于入库前工作树；本阶段改动已入库 commit 4243c6f）

- `pytest tests/desktop/test_visual_baseline_a.py -n 0` → 9 passed（多次）；`test_font_metric_baseline_a.py -n 0` → 4 passed（多次）
- `pytest tests/desktop`（默认 xdist）→ 839 passed 三连跑全绿（历史 2 次单红均为 startup_window 证据轨用例的时序二态，已在模块 docstring 登记）
- `ruff check tests/` → All checks passed；pyright 两新模块 → 0 errors
- 截图 PNG 9 张经 PIL 色彩统计抽查（非空/双主题差异显著/Info 面板 852 色），manifest.json 含 §9.3 全项元数据（源码 HEAD 112483c8、PySide6 6.11.0、ui_scale=1.0）
- 机器污染修复：网格 ×2 + tab_container ×1 用例钉 `_reduce_motion=False`，修后该文件全绿

无证据即 unverified——本文档自身也是这个纪律的适用对象。
