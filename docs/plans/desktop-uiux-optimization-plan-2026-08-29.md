# AssetManager 桌面端 UI/UX 设计优化方案（2026-08-29）
> 状态：**现行** · 状态登记：2026-09-02（文档整理轮补登）


> 前置输入：`docs/reports/desktop-uiux-review-2026-08-29.md`（同日评审，M1–M7/L 项与本方案 9 个问题一一对应）
> 方法：只读复核当前工作树（分支 `feat/quality-audit-2026-08-17`，HEAD=521372e），全部 file:line 为 2026-08-29 实测。
> 边界：本方案只做提案，不改任何源码、不跑测试、不做 git 写操作。评审后已落地的 4 项修复（7086bd3 删除确认默认按钮 / 8af0841 全局 QSS 原生控件 / 83e4eaf 缩略图失败可见化 / 762658c 托盘提示+单实例锁）**不再重复提案**，涉及处仅作依赖引用。
> 架构约束：所有方案遵守现有分层（panels mixin 星系 / signal_bus 7 信号 / domain event_bus / TabbedDialog / ThemeLoader+StyleKit / i18n tr() + en/zh/ja 各 861 keys / `scripts/check_style_sources.py` px 门禁），不提出推翻性重构。

---

## 0. 与历史清单的对账（避免重复立项）

历史 40 条清单（`docs/reports/ui-optimization-priority-2026-08-15.md` P0-1..P2-10 + `docs/reports/panel-uiux-composition-audit-2026-08-15.md` S-F1..12 / F-01..15 / I-01..13）中，与本方案 9 个问题直接衔接的条目：

| 本方案问题 | 衔接的历史条目 | 状态 |
|---|---|---|
| #2 标签去模态化 | P1-6（tag_tree 点击不导航）、P1-7（`get_tag_filter` 无消费方）、S-K1/S-K2 | 仍开放，本方案 #2 一并收口 |
| #4 空态行动化 | S-F10（sidebar 空态复用 widgets/empty.py）、I-05（info 三态分离）、panel-audit §4"三态空态模板"跨面板机会 | 仍开放，本方案 #4 以 file_list 为首个落点 |
| #5 错误分级 | I-09（info 异步失败静默）、F-06（Toast i18n，已修） | I-09 仍开放，纳入 #5 |
| #6 按钮层级 | S-F3/S-F6（ghost 变体统一按钮样式）方向一致，但"默认=primary"问题为 08-29 评审新增 | 新增 |
| #8 键盘可达性 | F-12（网格焦点指示）、I-04（chips 键盘可达） | F-12 纳入 #8① |
| #9 CJK 排版 | M6（tag_chip 英文硬编码）相关但独立 | 部分衔接 |

其余 P0/P2 历史条目（category token、StyleKit 单例、面包屑高亮等）不在本方案范围，维持原清单状态。

---

## 1. 设置对话框保存语义统一（评审 M1）

### 1.1 现状与证据

- settings_dialog 全部设置项**点击即存**：外观模式 `settings_dialog.py:296-314`（`_apply_mode` → `AppSettings.set+save` + `themes.set_theme`）、主题菜单 `:388-393/:427/:464`、背景效果 `:539-545`、语言 `:1056-1057`（`i18n.set_language` 即时全窗 retranslate）、UI 缩放 `:1059-1064`（即存 + `bus().ui_scale_changed` 全窗重建）、缩略图质量 `:1156-1158`。
- 底部却渲染 Ok/Cancel/Apply 三按钮：`tabbed_dialog.py:393-409`（QDialogButtonBox + `_apply_btn`）。`SettingsDialog` **没有任何 `_on_apply`/`_on_accept` override**（grep 零命中），基类语义为 `_on_apply` 空实现、`_on_accept = _on_apply + accept`（`tabbed_dialog.py:467-472`）→ **Ok 与 Cancel 行为完全等价**（都只是关窗），Cancel 给出"放弃更改"的假承诺，Apply 是冗余按钮。
- sharing_settings_dialog 是另一套标准：快照 diff（`:332-337`）→ 变更摘要行 + Discard/Apply 按钮联动 enable（`:339-365`）→ Apply 失败保持 dirty + Toast error（`:380-390`），并把变更分为 hot / restart / planned 三档文案（`:343-349`）。

### 1.2 设计选项

| 选项 | 内容 | 取舍 |
|---|---|---|
| A. 收敛到"即时生效" | settings_dialog 移除 Ok/Cancel/Apply，仅保留"完成/关闭"按钮；sharing 因有外部副作用（LAN 服务器启停/重启分档）保留 dirty 模式 | 保留主题/语言/缩放的**实时预览**价值；改动集中在按钮盒；用户失去"后悔药"——需要以低频可逆操作兜底（主题可切回、缩放有滑杆、语言可再切）。桌面设置类对话框（VS Code、系统设置）主流即此模式 |
| B. 收敛到 dirty-tracking | 推广 sharing 快照模式到 settings 六页 | 需为外观/缩放/语言建立快照+回滚（`themes.set_theme` 回滚要经历两次全窗重建，视觉抖动明显）；实时预览被延迟到 Apply，违背"所见即所得"动机；六页改造量约为 A 的 5 倍 |
| C. 混合明示 | 即时页隐藏 Apply、可回滚页用 dirty 条 | 页间标准不一致仍存在，只是"说清楚了"；实现成本 ≈ A+B 之和，状态机最复杂 |

### 1.3 推荐方案与理由

**选 A**：即时生效是这批设置项的**天然语义**（预览类：主题/背景/缩放；环境类：语言/缩略图质量），延迟应用不产生任何架构收益——dock 重建已有"三信号合并为一帧"的合并机制（`dock_factory.py:49-56`）。dirty-tracking 的真正价值在 sharing：变更会**对外产生副作用**（LAN 服务重启、端口变更）且分档（热更新/需重启/仅计划），摘要行 + Discard 是副作用确认，不是通用保存模式。统一原则表述为：

> **无外部副作用的设置 = 即时生效 + 关闭按钮；有外部副作用的设置 = dirty 追踪 + 摘要 + Apply/Discard。**

### 1.4 交互规格

- TabbedDialog 增加按钮盒模式参数（构造 kwarg 或类属性）：`buttons="ok_cancel_apply"（现默认，其他对话框不动）| "close"`。
- SettingsDialog 用 `buttons="close"`：单个 primary "完成"（新 i18n key `dialog.done`，三语），回车=关闭，Esc 保持 Qt 默认 reject。
- 迁移步骤（按序，每步可独立提交）：
  1. TabbedDialog 参数化按钮盒（默认值保持现状，零行为变化）；
  2. SettingsDialog 切 `buttons="close"`，删除 `_apply_btn` 依赖（settings 从未 override `_on_apply`，无逻辑损失）；
  3. sharing 侧将底部 Ok/Apply 与页内 Discard/Apply 的双轨收敛为：底部仅"关闭"，页内保留 Discard/Apply（关闭时若有未保存变更 → 沿用 `:392-395` 的 `_accept_configuration_changes` 语义改为询问，或先只做 settings 侧、sharing 二期）。
- 文案要点：`dialog.done` zh"完成" / en"Done" / ja"完了"；旧 key `dialog.apply`/`dialog.ok` 保留给其他对话框。

### 1.5 兼容与迁移风险

- 惯性风险：老用户在设置窗按 Ctrl+W/Esc 即走，无损失；唯一行为变化是"没有 Cancel 可点"，属预期。
- 测试面：若存在断言 settings 按钮盒结构的测试需同步（本次未发现 UI 结构测试钉死该区域，落地时以 grep 确认）。
- `settings_changed` 信号（`tabbed_dialog.py:162/:397`）在 settings 侧本就无人依赖 Apply 时机（全部即时保存），移除 Apply 无信号断链。

### 1.6 工作量：**S**（TabbedDialog 参数化 + settings 换模式 + 1 个 i18n key × 3）

---

## 2. 标签检索去模态化（评审 M2）

### 2.1 现状与证据

- TagBrowserDialog 是**一次性 picker**：`tag_browser_dialog.py:43-46` 点文件行 → `directory_selected.emit + accept()` 关窗；打开方式为应用模态 `info.py:1249-1256`（`dlg.exec()`，且 `directory_selected` 转发给 `info.navigate_requested`）。
- 模态锁死的检索模型：`tag_tree.py:36` `_active_tag_filter: str | None` 单值；点标签仅过滤标签树自身（`:211-214`）并 `bus().directory_changed.emit(library_root)`（`:213`）；`get_tag_filter()`（`:396-397`）**全仓无消费者**——即历史 P1-7 的"标签过滤开关点了无效"仍开放；点文件行 `directory_selected` + `directory_changed`（`:216-217`），历史 P1-6。
- 现有架构已为"窗内 tag_tree"留了完整的缝：
  - `dock_factory.py:38-43` PANELS 注册表含 `"tag_tree": ("dock.tag_tree", TagTreePanel)`；
  - `window.py:261-269` 注释明示 ""tag_tree" is intentionally absent as a mounted dock… This loop tolerates the missing attribute so a future in-window TagTreePanel slots in unchanged"（评审所引 236-239 行已因后续提交漂移至此），`window.py:265` 的 `for name in ("file_list","info","sidebar","tag_tree")` 会自动对挂载的 tag_tree 注入 scoped services；
  - 生命周期范本已有：`tag_browser_dialog.py:48-53` 的 shutdown 解绑模式。
- signal_bus 7 信号（`signal_bus.py:22-28`）中 `directory_changed/file_focused/refresh_requested` 是本问题的衔接点。

### 2.2 设计选项

| 选项 | 内容 | 取舍 |
|---|---|---|
| A. 非模态 dock（主窗停靠） | 恢复 tag_tree 为默认隐藏的 dock，info 标签区"浏览"按钮改为显示/聚焦 dock；检索与文件浏览并行 | dock 工厂/标题按钮/主题刷新/scoped services 全部现成（`dock_factory.create` 一行挂载）；符合"检索是持续活动"的心智；风险：与既有**有意设计决策**相悖，需在 ADR 记录决策反转理由；`_DOCK_TITLES` 重开库残留（dock_factory.py:46/:265，已知开放问题）会同样影响此 dock |
| B. 保留独立窗口，改非模态 | `dlg.exec()` → `dlg.show()`，去掉点行即关 | 改动最小（S）；但独立窗口脱离主窗 dock 体系，多窗口 Z 序/失焦管理要自己写，主题/缩放刷新链路要单独处理，长期是第二套维护面 |
| C. 侧边页/工作区标签页 | 并入 TabContainer 或主窗侧边 | tab_container 存在 restore_state 双循环未修（overview §12/§19 #6），在其上叠新面板风险最高；标签检索与"当前目录"心智也不匹配 |

### 2.3 推荐方案与理由

**选 A（dock 化，两阶段）**，并同步修订 window.py:261-269 的设计决策注释为 ADR。理由：基础设施预留完整（`window.py:265` 的容忍循环 + `dock_factory` 注册项），边际成本最低；标签检索本质是**与文件浏览并行的持续活动**（"看看有哪些打了 X 标签的文件，再切到 Y 标签"），模态 picker 与之根本冲突。B 作为 A 受阻时的兜底。

**分两阶段以控制风险**：

- **阶段 1（纯去模态，价值立现）**：挂载 tag_tree dock（默认隐藏）+ info"浏览标签"改为切换 dock 可见性；`_on_file_selected` 不再 accept 关窗，改为 `bus().file_focused.emit(path)` + 主窗导航；`directory_changed` 链路保持现状（`:216-217` 已 emit，file_list 侧已消费该信号导航）。
- **阶段 2（过滤语义，收口 P1-6/P1-7）**：给 signal_bus 新增第 8 信号 `tag_filter_changed(tuple[str, ...], str)`（标签集 + 模式 and/or），由 tag_tree 在点选标签时 emit；file_list 侧订阅并透传给 `_model.py` 新增的 tag 过滤参数（模型已有 text/category 过滤先例：`_model.py:416-418` `set_filter`、`:777` `set_filter_text`，扩一个 `set_filter_tags` 同构）；多选 AND/OR 用标签行 checkbox + 工具行切换按钮明示（替换现在"点标签=过滤树自己"的歧义行为 `:211-214`）。**删除 `get_tag_filter()` 或接上消费者**，消除 P1-7 死接口。

### 2.4 交互规格

- 状态：tag dock 三态 = 隐藏（默认，新库首开）/ 显示无过滤 / 显示有过滤。转移：info 标签区"浏览"按钮 ↔ 切换；dock 关闭钮 → 隐藏（不销毁，scoped services 保持）；换库 → 沿 `tag_tree.py:348-349/:393` 现有清过滤逻辑，dock 回隐藏态。
- 点击标签行 = 勾选/取消该标签进过滤集（阶段 2），树内文件子列表 = 该标签文件预览；点击文件行 = `file_focused` + 主窗导航，**不关窗**。
- 文案要点：过滤激活时 dock 标题或工具行显示计数（`tagbrowser.filter_active`，带 `{count}` 占位）；清除过滤按钮沿用 `__clear_filter__` 项（`:180-183/:206-210`）。i18n 新增 keys 建议 ≤8 个 ×3 语。
- a11y：树节点补 accessibleName（现仅 tooltip，`:199`）。

### 2.5 兼容与迁移风险

- **决策反转需留痕**：window.py:261-269 注释是有意设计，落地时同步 ADR（docs/adr/ 已有 0001-0003 惯例）说明"模态 picker 代价 > dock 复杂度"的权衡。
- 生命周期：dock 常驻意味着 TagTreePanel 的 bus 订阅与 scoped services 注入走 window.py:265 现成路径，但 **shutdown 时机**从"对话框关闭"变为"换库/关窗"，须复用 `tag_browser_dialog.py:48-53` 的 shutdown 模式并在 close_library 链路验证（评审"仍开放"清单中的关窗串行 drain 问题会叠加，需真机回归）。
- `_DOCK_TITLES` 残留 bug（dock_factory.py:46/:265）会在此 dock 上复现（重开库标题滞留），建议作为前置小修。
- signal_bus 新信号属"presentation-only"契约扩展，须同步 signal_bus.py:6-14 的 Signal Reference 注释。

### 2.6 工作量：阶段 1 **M**（挂载 + 去模态 + 导航衔接）；阶段 2 **L**（模型 tag 过滤 + AND/OR + 死接口收口）

---

## 3. 撤销可发现性：把"Ctrl+Z 可撤销"说出来（评审 M4）

### 3.1 现状与证据

- 撤销栈完整但不可见：删除已入撤销栈（ed68f7e，见 git log），确认框在撤销服务缺失时会**拒绝执行**以兑现"可撤销"承诺（`_actions.py:457-466`）——但操作完成后 UI 无任何"可撤销"提示。
- 反馈通道现状：操作反馈只进状态栏一行 muted 文本，4s 后消失（`_base_logic.py:262-295` `_show_operation_feedback` + `_base_events.py:150-153` 4s timer），文案由 `_status_helpers.py:39-75` 从 `filelist.feedback.*` 选取；**无撤销语义**。
- Toast 体系已备好但未接入：`widgets/toast.py` 三级（info/success/error）+ QAccessible Alert 播报（`:250-257/:347-352`）+ 单例替换（`:188-202`）；file_list 中仅 `_base_layout.py:411` 搜索结果一处使用，`_actions.py` **Toast 零命中**（grep 实证）。
- 撤销入口已存在：`_undo`（`_actions.py:643-675`）+ Ctrl+Z 已注册（`_commands.py:44`）。

### 3.2 设计选项

| 选项 | 内容 | 取舍 |
|---|---|---|
| A. 状态栏反馈追加撤销后缀 | `_show_operation_feedback` 完成分支在成功且 `can_undo()` 时追加 " · Ctrl+Z 撤销" 后缀 | S 级、零新组件、沿既有 4s 通道天然限频；缺点是 muted 小字，可发现性提升有限 |
| B. 完成时弹 Toast（带"撤销"动作按钮） | 删除/移动类高危操作完成后 Toast success + 动作按钮点击即 `_undo` | 可发现性最高（Gmail 模式）；但 toast.py 无动作按钮能力（`:46-135` 仅 message/subtitle/icon），需扩展组件；且 Toast 单例每 3s 一换，批量操作会互相顶掉 |
| C. A+B 分级 | 常规操作用 A；删除类（trash/permanent_delete 不可撤销除外）用 B | 分级合理，工作量 = A + B |

### 3.3 推荐方案与理由

**C（先 A 后 B）**。理由：A 是纯文案层改动，立刻让"可撤销"被看见，且状态栏通道已有的会话校验（`_is_current_operation_session`，`:273-276`）天然防止陈旧反馈；B 的 Toast 动作按钮是通用能力（后续错误重试等也能用），值得做但不阻塞 A。

### 3.4 交互规格

- **接入点（A）**：`_base_logic.py:277-284` 处，`running=False and not errors and changed_count>0 and undo_service.can_undo()` 时 `text = text + tr("filelist.feedback.undo_hint")`。覆盖操作：paste/rename/trash/new_folder/duplicate/batch_rename/drop（`_actions.py:273/:361/:432/:593/:630/:833` + `_base_logic.py:737`）。permanent_delete 与 undo/redo 自身**不加**后缀（不可撤销/语义自指）。
- **接入点（B，二期）**：`_on_trash_done`（`_actions.py:422-440` 分支）成功时 `Toast.success(..., subtitle=tr("filelist.toast.undo_subtitle"), action=...)`；Toast 扩展构造参数 `action_text/action_callback`（动作按钮 + 键盘可达 + a11n 播报动作名）。防顶掉：删除类 Toast 时长提高到 6s。
- **防打扰策略**（两级）：① 每会话每操作类型只弹一次 Toast 动作提示（`AppSettings` 会话内 set 或面板实例字典），后继同型操作退回状态栏后缀（A 通道）；② 状态栏后缀不限频（4s 自动消失，muted 色，不构成打断）。不弹"已删除 N 项"成功 Toast 常态化——只保留删除类 + 首次提示，避免 Toast 变成噪音源。
- **文案规范**：
  - `filelist.feedback.undo_hint`：zh " · Ctrl+Z 可撤销" / en " · Ctrl+Z to undo" / ja " · Ctrl+Z で元に戻す"（作为后缀模板，含引导符，避免拼接逻辑）。
  - Toast 动作按钮文案 = `filelist.menu.undo`（复用既有 key）。
  - 键位显示来源：Phase 2（#8②）注册表收敛后改为从注册表取当前绑定，防 QWERTY 假设漂移（M7 关联）。
- i18n：新增 2 keys（undo_hint、toast.undo_subtitle）×3 语；命名占位符规范沿用。

### 3.5 兼容与迁移风险

- `operation_feedback_text` 是纯函数且有既有语义（`_status_helpers.py:39-75`），后缀拼接放在调用方（`_show_operation_feedback`）而非纯函数内，保持纯函数可测性。
- Toast 动作按钮版本需处理 parent 生命周期（现 eventFilter 已处理 parent hide/close，`:331-345`，动作回调须弱引用 panel，避免 Toast 比面板长寿）。
- 状态栏一行空间有限：缩放 0.5× 下后缀可能被裁切，文案用" · Ctrl+Z"短形，完整语义由 tooltip 承担（可选）。

### 3.6 工作量：A **S**；B **M**（toast.py 扩展 + 首次提示限频 + a11y）

---

## 4. 空态/错误态行动化（评审 M5）

### 4.1 现状与证据

- 四态各为一行灰字：`_status_helpers.py:24-36`（loading/scan_error/empty_folder/empty_filtered → `filelist.state.*`/`filelist.empty`），由 `_base_layout.py:442-468` `_update_status` 写进 `_status` QLabel；`:470-474` `_show_empty_if_needed` 同样只改文字。错误态无重试、空目录无动作、过滤空无清除。
- 引导组件已存在但零复用于 file_list：`panels/empty.py:13-85` EmptyPanel（语义图标 + 标题 + 副标题 `:36-38`，`for_loading/for_error` 工厂 `:59-85`）；但 ① 无动作按钮槽位；② 工厂用 `findChildren` + 字面 "Empty" 文本匹配替换实现（`:66-70/:80-84`），脆弱且与 M6（`_detail_model.py:279` 以英文 "Empty" 做解析）同源。
- 视图容器结构：grid 与 detail 是兄弟控件按可见性切换（`_base_layout.py:217-219`、`:262-263`；`_base_events.py:219-220`），没有现成 overlay 层。

### 4.2 设计选项

| 选项 | 内容 | 取舍 |
|---|---|---|
| A. 状态栏按钮化 | 四态时在状态栏右侧内联小按钮（重试/清除过滤/新建/返回上级） | 改动最小；但动作藏在 28px 底条里，可发现性差，与"行动化"目标错位 |
| B. 中央空态覆盖层 | 复用/扩展 EmptyPanel 为可含动作按钮的空态卡，四态时覆盖在 grid/detail 之上，恢复后隐藏 | 视觉权威、动作显性；需要 overlay 插入/移除时序与两视图同步 |
| C. 就地替换视图内容 | 空态时把 grid/detail 换成 EmptyPanel（addWidget 切换） | 与 `setVisible` 切换机制纠缠最少；但焦点/滚动位置/选中恢复路径要小心 |

### 4.3 推荐方案与理由

**B**，实现走 "overlay widget + `setVisible`"：将 EmptyPanel 升级为 `EmptyState(icon, title, subtitle, actions=[(label, callback), ...])`，以 `content_layout.insertWidget(index_of(grid), overlay)` 方式插入（与 `:217-219` 同法），四态时显示对应 overlay 并隐藏当前视图。理由：动作与解释同屏（重试按钮贴着错误原因），是"行动化空态"的标准形态；且 panel-audit §4 已把"三态空态模板"列为跨面板机会，先在 file_list 落地成可复用组件，sidebar（S-F10）/info（I-05）后续接入。

### 4.4 交互规格

| 状态 | 标题（muted→语义色） | 动作按钮（primary→ghost 排序） | 触发回调 |
|---|---|---|---|
| loading | filelist.state.loading + 时钟图标（`for_loading` 现成） | 无（骨架留白即可，本方案不加 spinner） | — |
| scan_error | filelist.state.scan_error + danger 图标 | 1) 重试（primary） 2) 返回上级（ghost，仅非根目录） | `_do_refresh` / `_go_up` |
| empty_folder | filelist.empty | 1) 新建文件夹（primary） 2) 返回上级（ghost，仅非根） | `_new_folder`（`_actions.py:572` 一带）/ `_go_up` |
| empty_filtered | filelist.state.empty_filtered | 1) 清除过滤（primary） 2) 清除搜索（ghost，当 `_search.text()` 非空） | 重置 `_filter_combo` + `set_filter_text("")` + `_search.clear()` |

- 转移：四态判定仍以 `_model.list_state`（`_model.py:94` 一带 STATE_*）为唯一事实源，`_update_status`（`_base_layout.py:442`）内加"overlay 同步"分支；状态栏文字**保留**（读屏与窄窗口兜底）。
- 焦点：overlay 显示时把焦点交给第一个动作按钮（键盘不丢）；Esc 在 empty_filtered 态 = 清除过滤（与 `_shortcuts.py:39-46` 现语义一致）。
- 文案要点：动作按钮文案复用既有 keys（`filelist.menu.new_folder`/`filelist.menu.refresh`/`filelist.help.up` 等）+ 新增 `filelist.action.clear_filter` ×3 语；empty_filtered 标题可加 `{filter}` 占位显示当前过滤类别。
- 组件化顺手修：EmptyPanel 工厂去掉 `findChildren`+字面 "Empty" 匹配（`empty.py:66-70/:80-84`），改显式 label 引用——消除与 `_detail_model.py:279` 同类的英文文案耦合（M6 局部收口）。

### 4.5 兼容与迁移风险

- overlay 与 detail/grid 的可见性互斥要处理"切视图瞬间 overlay 闪现"：以 `list_state` 驱动而非视图切换驱动。
- 空态下拖放（drop 新文件）仍需落在 overlay 之下：overlay 设 `setAttribute(WA_TransparentForMouseEvents)` 之外要放行 dragEnter/drop（或 overlay 仅覆盖非拖放区），与 H4 拖放语义修复联动验收。
- 测试：`tests/desktop/test_file_list_grid_widget.py` 若锁定了 `_status` 行为需回归；新增 overlay 逻辑建议纯逻辑函数（state→actions 映射）单测。

### 4.6 工作量：**M**（EmptyState 组件 + file_list 四态接线 + i18n ×3；sidebar/info 复用另计）

---

## 5. 错误呈现分级规范（评审 M3）

### 5.1 现状与证据

- 实测统计（grep 当前树）：`QMessageBox.warning` **50 处**、`.critical` 7、`.information` 16、`.question` 12、`setDetailedText` **0**。warning 大量用于非警告语义（如主题重名 `settings_dialog.py:430` 一带）。
- 同一句话弹弹幕：`settings.error_no_library` 在 settings_dialog 引用 **10 处**（7 处 `QMessageBox.warning`：`:786/:805/:832/:925/:936/:948/:1170`；3 处状态文本：`:878/:961/:965`）——维护页每个按钮在无库时各自弹一次。
- 行内校验孤例：`sharing_settings_dialog.py:1151-1161` `_auth_error_label`（+ Toast error 双报）。DetailedText/可复制能力全库为零。
- info 面板备注自动保存：成功静默、失败仅日志（`info.py:1404-1433`，评审 I-09 同源）。

### 5.2 决策表（本方案的核心交付物）

| 场景 | 载体 | 默认按钮/焦点 | 可复制 | 备注 |
|---|---|---|---|---|
| 输入校验（焦点在场、可立即改） | **行内** error label + 控件描边（ sharing `_auth_error_label` 范本） | — | — | 禁用提交按钮直至合法，而非弹窗拦截 |
| 破坏性确认（删除/覆盖/重启服务） | **模态 question** | 默认 **No**（7086bd3 已全量修复，保持） | 文本可选中 | 兑现可撤销则必须能走撤销栈（`_actions.py:457-466` 范本） |
| 操作完成（成功/部分成功） | **状态栏** 或 success Toast（#3 规范） | — | — | 不用 information 弹窗打断 |
| 就地可重试失败（扫描失败、缩略图失败、备注保存失败） | **空态/状态栏错误色 + 重试按钮**（#4 组件） | — | 失败原因入 tooltip | info.py:1404-1433 备注保存失败 → 首次 Toast error + 状态行常驻重试入口 |
| 环境性前置缺失（无库/无服务/无权限） | **行内禁用 + 说明**：禁用触发按钮 + 就地解释 label，绝不逐按钮弹窗 | — | — | error_no_library 全部行内化（见下） |
| 需要用户离开当前流程的失败 | **error Toast**（不可恢复时升级模态 critical） | — | 详情可复制 | Toast 已有 QAccessible Alert |
| 致命错误（数据损坏、恢复失败） | **模态 critical + DetailedText**（技术详情折叠，可复制） | OK | **必须** | 全库 7 处 critical 统一补 `setDetailedText` |

### 5.3 设置对话框行内化改造方案

1. 维护/备份页（`:720/:779` 两页）初始化时检测 `library_settings_adapter` 可用性：不可用 → 整组 `setEnabled(False)` + 组内顶部 muted/error 行内说明（复用 `:878/:961/:965` 已有的 status label，改为常显）；7 处 `QMessageBox.warning(error_no_library)` 全部删除（`:786/:805/:832/:925/:936/:948/:1170`）。
2. 主题重名等"用户输入冲突"（`:430` 一带）：warning → 行内 error label（名称输入框下方），弹窗清零。
3. critical 7 处统一 `setDetailedText(异常链)` + `setTextFormat(PlainText)`；同时把标题/正文改为"发生了什么 + 用户能做什么"两段式。
4. i18n：新增"无库说明"行内版 key（`settings.error_no_library.inline`，语义改为说明句而非报错句）×3 语；删除 7 处弹窗不删 key（状态文本 3 处仍用）。

### 5.4 兼容与迁移风险

- 行为变化点：无库时维护按钮从"点了弹错"变为"灰色不可点"——更符合防御式 UI，但依赖"adapter 可用性检测"与 `MaintenanceChanged` 订阅（`settings_dialog.py:1035-1054`）时机一致，需在开库/关库往返中回归。
- 分级表落地不需要新框架：Toast/行内 label/QMessageBox 三通道全部现成，属**使用规范**而非组件建设；建议把决策表摘录进 docs/development.md 的 UI 章节，供后续 PR 自查。
- 残余 risk：50 处 warning 不可能一次清零，落地按"settings 全量 + 其余按触点顺带"推进，避免大爆炸 PR。

### 5.5 工作量：决策表+settings 行内化 **M**；critical DetailedText 统一 **S**；全库 warning 治理 **L**（可分期，随触点顺带）

---

## 6. 按钮视觉层级：默认变体策略（评审 L 项 → 本方案升级为结构性问题）

### 6.1 现状与证据

- 全局 QSS 默认 `QPushButton` = accent 主色实心（`core/themes.py:626-633`），四个语义变体 primary/secondary/ghost/danger 仅在显式设 `buttonVariant` 属性时生效（`:634-666`；`set_button_variant` 实现 `themes.py:426-442`）。**"没设 variant" 与 "primary" 渲染完全相同**——评审渲染目检证实二者同色，视觉层级被抹平。
- 双源问题：StyleKit `dialog_css()` 内部也定义了同一套默认 accent 按钮（`widgets/stylekit.py:377-380` + 变体 `:381-410`）——改默认必须**两处同步**，否则对话框内（走 dialog_css）与主窗（走全局 QSS）分叉。
- 迁移面实测：
  - `QPushButton(` 直接创建 **54 处 / 25 文件**（info.py 7、theme_preview.py 6、theme_preview_dialog/tag_style_dialog/tabbed_dialog 各 4、sidebar/startup/settings 各 3，余为 1-2 处）；
  - `QDialogButtonBox` 5 文件（tabbed_dialog/sharing/plugin_operator/sidebar_settings/batch_rename）；
  - 显式 `set_button_variant` 调用 **20 处 / 12 文件**（tabbed_dialog 6、dock_factory 3，余各 1）→ 约 2/3 以上按钮创建点依赖默认样式。
- `check_style_sources.py` 门禁只管 px/token/拼接，不约束 variant，改动无门禁冲突。

### 6.2 设计选项

| 选项 | 内容 | 取舍 |
|---|---|---|
| A. 默认改 secondary | 全局 QSS + dialog_css 的裸 `QPushButton` 规则改为 secondary 视觉；primary 仅显式声明 | 迁移面 = 2 处 QSS + 对 54 处创建点做一次"是否需要 primary"的目检批量确认；危险默认值反转（什么都不设 = 安全低调）；已有显式 primary 的 20 处不受影响 |
| B. 默认保持 primary，次要按钮显式 secondary | 反向标注 | 需要在 ~34+ 处显式标注，且**新增按钮默认仍是主色**——同类问题会持续再生，与 S-F3/S-F6 的 ghost 统一方向背道而驰 |
| C. 引入 Qt default-button 联动 | 默认按钮（回车触发）自动 primary，其余 secondary | 语义最正确但实现最重（Qt 的 default 属性与 QSS 伪态组合易碎），且非对话框场景无 default 概念 |

### 6.3 推荐方案与理由

**A**。原则表述：

> **默认样式 = secondary（低调、带边框）；primary 只给每个视图/对话框的单一主动作；ghost 给工具行/标题栏图标动作；danger 只给破坏性动作。**

改动落点：`themes.py:626-633` 裸规则改为 secondary 外观（或直接让裸规则等价于 `buttonVariant="secondary"` 的声明复制），`stylekit.py:377-380` 同步；`:407` 的 focus 规则（2px border_focus）两处保持。随后对 54 处创建点做一次批量目检，把真正的"主动作"显式 `set_button_variant(btn, "primary")`（预估 10-15 处：各对话框右下确认、info Actions 栏主按钮、startup 开始按钮等）。

### 6.4 交互规格

- 视觉规格（沿用现 secondary 定义 `themes.py:643-652`）：panel 底 + hairline 边 + heading 前景，hover=hover_overlay，pressed=accent 18% alpha。
- 回车触发的主按钮仍应 primary（如 TabbedDialog Ok，已显式 primary `tabbed_dialog.py:405`）——变体与 default-button 职责分离，不引入 C 的联动机制。
- danger 变体沿用；删除类上下文菜单不受影响（QMenu action 非 QPushButton）。

### 6.5 兼容与迁移风险

- **视觉回归面是最大风险**：54 处按钮同时变色，需要 offscreen 渲染对照（复用评审 `tmp/ux_review/render_gallery.py` 方法）逐面板目检一遍，尤其 tag_chip/tab_container/workspace_bar 等小尺寸按钮（padding 缩小后 hit area 检查）。
- 插件生态：`Plugins/` 若有依赖默认按钮样式的第三方 UI，主题热重载后观感变化属可接受语义（主题契约里 primary 从来是显式属性）。
- i18n 无涉。px 门禁无涉。

### 6.6 工作量：**M**（2 处 QSS 改动很小，但 54 处目检 + 渲染回归占大头）

---

## 7. 新增低密度列表视图（评审 L 项 + README 不符）

### 7.1 现状与证据

- 视图仅两种：`_base_layout.py:148-153` `_view_combo` 只有 Grid/Details 两项；切换为两个兄弟控件可见性互换（`_base_events.py:206-230` `_on_view_changed`：`is_detail = mode == "Details"` 二分支），按目录记忆（`:208` `_view_memory`）。
- 详情视图本体：QTreeView + DetailModel 5 列（`_base_layout.py:225-263`；`_detail_model.py:131` `columnCount = len(HEADER_KEYS)`，`:201-205` header i18n），行高 32sp（`_ui_helpers.py:27-33` delegate）。
- README.md:35 宣称"网格/列表/详情"三种——`check_doc_stats.py` 不校验该句，属文档超前于实现。

### 7.2 设计选项

| 选项 | 内容 | 取舍 |
|---|---|---|
| A. 独立 List 视图 | QListView + 轻量 model（名称+图标+可选大小） | 信息架构最清晰；但 `_on_view_changed` 从二分支变三分支，选中同步（`:211-229` 网格/详情双向迁移）、拖放、keyPressEvent 分派（`_shortcuts.py:15` `is_details` 判定）全部要三态化——交互路径分叉成本远超组件本身 |
| B. List = Details 的紧凑预设 | 第三 combo 项 `userData="List"`，内部仍走 Details 分支：隐藏"类型/修改日期"列（仅 名称+大小 或纯名称）、行高 32→22、图标 18→14 | **零交互路径分叉**：`is_details = mode != "Grid"`，所有既有同步/快捷键/拖放逻辑原样生效；QTreeView 列显隐 + delegate 行高参数化即可；与"详情视图降密度"殊途同归但以独立选项呈现 |
| C. 网格 zoom 最小档 | 调低 ZOOM_PRESETS 下限让网格卡变密 | 改动最小但仍是卡片（占位缩略图空间在），不构成"列表"信息密度，README 依然失真 |

### 7.3 推荐方案与理由

**B（独立选项、共享实现）**：用户看到第三种视图（README 对齐），实现上是 Details 的列/密度预设——把"独立视图"的产品价值与"不分叉状态机"的工程价值同时拿到。若未来确需真正独立的 List model（如行内标签列），B 的 `mode != "Grid"` 收敛已经为 A 铺好了三分支迁移点。

### 7.4 交互规格

- combo 第三项：`tr("filelist.view.list")` / `userData="List"`（`_base_layout.py:149-150` 处追加；`_retranslate_controls` `:403-408` 同步第三项文案）。
- 进入 List：`_detail_view.setVisible(True)` 同 Details，差异施加于——列显隐（`header.setSectionHidden`，保留 名称+大小；`_detail_model.HEADER_KEYS` 不动）、行高（delegate `:27-33` 参数化 `sizeHint` 高度 22sp）、图标尺寸 `setIconSize(14px scaled)`、停用交替行色（密度感）。
- 记忆：`_view_memory`（`:208`）与持久化（`_base.py:73` "view" key）自动兼容新值；旧值迁移无需处理（findData 兜底）。
- 键盘/读屏：与 Details 完全一致（QTableView 原生可达，正好是 #8③ 自绘网格之外的无障碍替代路径，交互规格注明）。
- i18n：`filelist.view.list` ×3 语。

### 7.5 兼容与迁移风险

- `_on_view_changed` 中 `self._loader.set_size(self._thumb_size)`（`:209`）在 List 态应跳过缩略图预算（List 不画缩略图）：需在 loader 侧确认 List 态不请求缩略图（decoration 已不走 loader 大图，18→14px 图标走 icon_for 缓存，风险低）。
- 列显隐是视图级状态而非模型级，切回 Details 需恢复列——实现为"进入时施加、离开时恢复"，用一次 `restore` 快照，避免永久污染。
- 排序交互（`sort()` `_detail_model.py:207`）在隐藏列上禁用 sortIndicator，防"点隐藏列头"歧义。

### 7.6 工作量：**M**

---

## 8. 键盘可达性路线图（评审 H6 残留 + M7）

### 8.1 现状与证据

- **逐项读屏缺失（作者自注 follow-up）**：自绘网格仅容器级基线——accessibleName + 计数描述 + Alert 播报（`_grid_widget_data.py:95-146`，注释明言 "Per-item virtual-table interfaces are tracked as follow-up work" `:102`）；基线被 `tests/desktop/test_file_list_grid_a11y.py:45-123` 六个测试钉死，演进须同步扩基线。
- **焦点样式缺口**：全局 QSS 只有 `QLineEdit/QTextEdit/QSpinBox:focus`（`themes.py:614`）与 `QPushButton:focus`（`:633`，1px 边框**替换式**，会引起 1px 布局抖动）；`QComboBox:focus`、`QCheckBox/QRadioButton:focus` 全局缺失（评审 H6）。**stylekit 局部样式已有正确范本**：`widgets/stylekit.py:315`（QComboBox:focus）、`:337/:346/:355`（check/radio focus）——只差搬进全局。
- **快捷键三源**：① `_commands.py:29-51` `FILE_LIST_SHORTCUTS` 19 条自称 "single source of truth"；② `_shortcuts.py:8-47` `handle_key` 手工分派（Backspace/Escape/Ctrl+F 三条游离于表外）；③ F4 帮助对话框 15 行手写列表（`_base_layout.py:661-686`），与 ① 并不完全一致（合并行、缺 F4 自身条目等）。全局注册表 `ShortcutManager`（`widgets/shortcut_manager.py:28-35` defaults + `:63-71` 冲突 warn-and-replace）只收录菜单级快捷键（`window.py:477-499` F1 帮助由注册表生成）；冲突检测无跨作用域门禁、全程未用 `QKeySequence::StandardKey`。

### 8.2 设计选项与推荐（本问题按四个独立子项推进，各附推荐）

**① 焦点样式补齐（S，先做——所有键盘工作的前置）**
推荐：把 stylekit 的 focus 规则上提进全局 QSS（`themes.py:609-633` 区域）：`QComboBox:focus`（1px border_focus 即可，避免 stylekit 的 2px 造成与全局 1px 边框体系不一致）、`QCheckBox/QRadioButton:focus`（沿用 stylekit 的"文字变色 + indicator 描边"方案 `:337/:346/:355`，**非几何替换**，零抖动）；同时把 `QPushButton:focus`（`:633`）与 `QLineEdit:focus`（`:614`）的替换式 1px 边框改为"外描边"式（padding 内缩 1px 补偿或 outline），消除焦点抖动。风险：全局视觉回归一批控件，随 #6 的渲染目检同车验收。

**② 快捷键注册表收敛（M）**
推荐：`FILE_LIST_SHORTCUTS` 作为**数据源**在面板初始化时批量注册进 ShortcutManager（`category="filelist"`，注册表已有 category 字段 `:79/:150-156`），F4 帮助改为**由注册表按 category 生成**（复用 F1 帮助的渲染路径 `window.py:134-146`），删除 `_base_layout.py:661-686` 手写 15 行。`handle_key`（`_shortcuts.py`）保留为**分派器**（自绘画布无法用 QShortcut 精确作用域，keyPressEvent 是对的），但 19 条映射以 `shortcut_command_id` 为准、表外三条（Backspace/Escape/Ctrl+F）补进 FILE_LIST_SHORTCUTS 使文档=实现。风险：F4 首次提示逻辑（`filelist_shortcut_hints_seen` 设置键 `:669-672`）保留；注册表新增条目会出现在 F1 帮助中（预期收益）。

**③ 网格逐项读屏（L，真机验证驱动）**
推荐分两档：
- 档 1（务实，M）：实现最小 `QAccessibleTableInterface`（rows=条目数，cells=名称/类型两列）或退一步用 `QAccessible.List`/`Selection` 接口 + 方向键导航时以 Alert 播报"当前项：{名}"（复用 `_a11y_announce_selection_now` 防抖模式 `_grid_widget_data.py:127-146`）。读屏用户可逐项遍历。
- 档 2（完整，L）：完整虚拟表接口 + 选中/悬停事件映射，NVDA/JAWS/Narrator 三读屏真机矩阵验证（offscreen 不可信，评审已证）。
- 测试：`test_file_list_grid_a11y.py` 基线扩为"容器 + 逐项"两层；mock QAccessible 的既有 monkeypatch 模式（`:80` 一带）可复用。

**④ StandardKey 对齐（M，可延后）**
推荐：Copy/Cut/Paste/Undo/Redo/SelectAll/Refresh 七条改用 `QKeySequence.StandardKey` 作为**默认值**，注册表存 override——解决非 QWERTY（AZERTY 等）布局下 Ctrl+Z/Y 类硬编码问题。与 ② 同车落地（注册表数据结构加 `standard_key` 可选字段）。

### 8.3 兼容与迁移风险

- ①影响所有对话框/面板焦点观感；②影响 F1/F4 两个帮助页内容与 `filelist_shortcut_hints_seen` 流程；③测试基线必须同步（评审已提示测试钉死现状）；④键位变化可能触及既有用户的肌肉记忆——StandardKey 在 Windows 上与现键位基本重合，风险低。
- 依赖关系：③档 1 依赖 ①（键盘遍历需可见焦点环）；②与 ④ 同车；A11y 档 2 需真机设备计划，建议单独立项。

### 8.4 工作量：① **S**；② **M**；③ 档 1 **M**/档 2 **L**；④ **M**

---

## 9. CJK 排版保障（评审 L 项，本方案给出规范与落点）

### 9.1 现状与证据

- **零显式字体配置**：全仓 `font-family` 0 处（grep 实证）；应用字体仅设 hinting 与字号（`app.py:91-98`），缩放刷新也只调 pointSize（`window.py:1195-1199`）——CJK 渲染完全依赖 Qt/OS 隐式回退，24 主题 × 3 语言矩阵下观感不可控（评审 offscreen"豆腐块"假象排查时已建议真机复核 zh/ja）。
- **字号下限对 CJK 过小**：`core/ui_scale.py:22-29`——`scaled_px` 下限 1px，`scaled_pt` 下限 **6pt**；0.5× 缩放时 12pt→6pt（≈8px），CJK 笔画在 8px 不可读（拉丁文尚可辨认）。全局 QSS 的 `f_sm=scaled_pt(12)`（`themes.py:564`）与网格自绘字号 `scaled_pt(9)/scaled_pt(8)`（`_grid_widget_data.py:82-90`）都受此下限影响。
- **半角冒号拼接**：`_actions.py:889-894`（属性对话框 5 行 "名称: 值"），zh/ja 排版惯例为全角冒号；同模式散布于状态/tooltip 拼接处。tag_chip 英文硬编码（`widgets/tag_chip.py:78/:106-128`，M6）是同家族问题的英文侧。

### 9.2 设计选项与推荐（三个子项）

**① 显式字体回退链（S）**
推荐：在 app 启动时设置应用级字体族链（`QFont.setFamilies`，`app.py:91-98` 处），按 UI 语言与平台取链：zh → `["Microsoft YaHei UI", "Segoe UI", sans-serif]`、ja → `["Yu Gothic UI", "Meiryo", "Segoe UI", sans-serif]`、en → `["Segoe UI", ...]`；语言切换（`i18n.set_language`）时刷新。不做 per-widget setFont（破坏级联与缩放体系），不做主题 JSON 字体字段（留作后续扩展点）。落点唯一（app.py + language_changed 挂钩），`check_style_sources` 无涉。

**② scaled_pt 下限提升（S）**
推荐：`ui_scale.py:29` 下限 6→**9pt**（0.5× 时 12pt→9pt≈12px，CJK 可辨认的下限）；同时 `scaled_pt` 增加可选 `floor` 参数供特例（网格 badge 8pt→维持 8 下限有理由时可显式传参，避免一刀切破坏现有布局断言）。风险：0.5× 用户整体字变大一点——属正确方向；固定尺寸控件以 `scaled_px` 为主（已达标，ui-optimization-priority 基线节确认），不受 pt 下限影响。

**③ "标签：值"拼接规范化（S）**
推荐：规范——**凡 label 与 value 拼接，必须走 per-language 模板 key，不允许代码里写字面 `": "`**。落地：新增通用 key `common.label_value = "{label}：{value}"`（zh/ja 全角）/ `"{label}: {value}"`（en），`_actions.py:889-894` 五行改用 `tr("common.label_value", label=tr(...), value=...)`；全仓 grep `f"{tr(` + `: ` 顺带清理。i18n 新增 1 key ×3 语。M6 的英文硬编码（tag_chip/theme_preview）另案（评审 M6 已列），本子项只管冒号拼接家族。

### 9.3 兼容与迁移风险

- ①需在 Win11 zh/ja/en 三环境真机目检（评审假象排除记录 §3 的教训：offscreen 字库不可信）。
- ②可能触发依赖 6pt 的极端布局断言（自绘卡片 `_t_h` 文本高度 `:92`）——改动后跑一次网格渲染目检即可覆盖。
- ③属性对话框信息行变宽，无布局风险；模板 key 属 861 → 862 keys，`check_doc_stats.py` 计数口径自动跟随（三语必须同增，否则计数门禁失败——这正是现存的键集 parity 缺口被计数门禁部分兜住的地方）。

### 9.4 工作量：① **S**；② **S**；③ **S**

---

## 10. 优先级路线图

排序原则：用户价值 ÷（成本 × 风险）。风险含视觉回归面、架构耦合、测试基线同步。

### 批次 1 · 快赢（互相独立，可并行，合计约 1-2 个会话）

| 项 | 问题# | 价值 | 成本 | 风险 | 依赖 |
|---|---|---|---|---|---|
| 8① 焦点样式补齐（含 focus 抖动修复） | 8 | 键盘用户全程受益，是 8③ 前置 | S | 低（渲染目检兜底） | 无 |
| 9① 字体回退链 + 9② pt 下限 + 9③ 冒号模板 | 9 | zh/ja 全量用户可读性 | S+S+S | 低（真机目检一次） | 无 |
| 3A 撤销提示状态栏后缀 | 3 | "暗功能"变可见，全操作受益 | S | 低 | 无 |
| 1 设置按钮语义（close 模式） | 1 | 消除假 Cancel 承诺 | S | 低 | TabbedDialog 参数化（含在本项内） |
| 5S critical 补 DetailedText | 5 | 错误可复制，支持成本下降 | S | 低 | 无 |

### 批次 2 · 结构改良（各自独立立项，3-4 个会话）

| 项 | 问题# | 价值 | 成本 | 风险 | 依赖 |
|---|---|---|---|---|---|
| 6 按钮默认=secondary + 54 处目检 | 6 | 视觉层级恢复，全应用观感 | M | 中（回归面大，与 8① 同车目检） | 建议在 8① 后做（合并目检） |
| 4 空态/错误态行动化（EmptyState 组件） | 4 | 四态从"告知"变"行动" | M | 中（拖放/焦点联动） | empty.py 顺手修（含在项内）；与 H4 拖放修复联动验收 |
| 5M settings 无库行内化 + 分级表入文档 | 5 | 消灭弹幕，规范固化 | M | 低 | 决策表先行（文档 PR） |
| 7 列表视图（Details 紧凑预设） | 7 | README 兑现 + 低密度场景 | M | 中低 | 无 |
| 8② 快捷键注册表收敛（+8④ StandardKey） | 8 | 三源归一，帮助页不再漂移 | M | 中低 | 无 |
| 3B Toast 动作按钮（删除类） | 3 | 高危操作一键撤销 | M | 中 | toast.py 扩展；文案依赖 8②（键位从注册表取）可选 |

### 批次 3 · 标签域与深水区（需决策/设备，另行排期）

| 项 | 问题# | 价值 | 成本 | 风险 | 依赖 |
|---|---|---|---|---|---|
| 2 阶段1 tag dock 化（去模态） | 2 | 标签检索解锁（P1-6 收口） | M | 中（决策反转 ADR + 生命周期回归） | 前置小修：`_DOCK_TITLES` 残留（dock_factory.py:46/:265） |
| 2 阶段2 tag 过滤进 file_list 模型（AND/OR） | 2 | 检索语义闭环（P1-7 收口） | L | 中高（新 signal + 模型过滤 + 树交互重构） | 阶段 1；signal_bus 契约注释同步 |
| 8③ 网格逐项读屏 档1 → 档2 | 8 | 读屏用户可用网格 | M→L | 高（测试基线 + 真机三读屏矩阵） | 8①；档 2 需真机设备计划，建议单独立项 |
| 5L 全库 warning 治理（50 处分期） | 5 | 分级纪律常态化 | L | 低（随触点顺带） | 决策表入 docs 后执行 |

### 依赖图（文字版）

- 地基：8①（焦点）→ 6（按钮目检同车）→ 8③档1；3B 键位文案 ← 8②。
- 独立可落地：1、3A、5S、9①②③、7。
- 串联：2 阶段1 → 2 阶段2；5 决策表 → 5M → 5L。
- 不依赖但建议同车验收：6 与 8①（同一次渲染目检覆盖按钮与焦点两批视觉变化）。

### 明确不做 / 暂缓

- 不推翻 mixin 面板架构、不动 tab_container（其双循环 bug 修复属 quality-audit 线，非 UI/UX 方案范围）。
- 不做"全库 50 处 warning 一次性大爆炸 PR"（分期顺带）。
- 不做主题 JSON 字体字段（等 9① 真机结论后再议）。

---

## 附：本方案引用的关键实测数字（2026-08-29 工作树）

- QMessageBox：warning 50 / critical 7 / information 16 / question 12 / setDetailedText 0；`settings.error_no_library` 10 处（7 弹窗 + 3 状态文本）。
- 按钮：`QPushButton(` 54 处/25 文件；`set_button_variant` 20 处/12 文件；`QDialogButtonBox` 5 文件；默认 accent 双源（themes.py:626 / stylekit.py:377）。
- i18n：en/zh/ja 各 **861** keys（实测）；TabbedDialog 子类 8 个；`_setup_tabs` 仅 settings_dialog。
- 视图：`_view_combo` 2 项（Grid/Details），`is_detail` 二分支（_base_events.py:210）；DetailModel 5 列。
- 快捷键：FILE_LIST_SHORTCUTS 19 条（_commands.py:31-51）；F4 手写列表 15 行（_base_layout.py:661-686）；ShortcutManager defaults 4 条。
- a11y 基线测试：tests/desktop/test_file_list_grid_a11y.py 6 个测试（:45-123）。
