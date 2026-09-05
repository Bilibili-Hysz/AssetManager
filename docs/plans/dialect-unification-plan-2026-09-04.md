# 代码风格与方言统一规划（2026-09-04）

> 状态：**PLAN（规划，未实施）** · 来源：`docs/deep-analysis-2026-09-04/` 全库深读（9 文档、7 并行勘察代理）+ 本日方言专项实证；全部锚点为 2026-09-04 工作树实测。
> 范围声明：本文只规划"同一意图存在多种写法"的收敛；纯架构债（巨石拆分、HTTP 自环等）只列入附录 D 不展开。
> 原则：**每个统一项必须有一个机械化防回退门禁**（棘轮脚本 / 静态检查 / 冻结签名），否则不开始——这是本项目 setStyleSheet 棘轮、layer DAG 例外表清零已验证有效的模式。

---

## 0. 一页结论

全库方言问题共识别 **12 类**，其中：

- **3 类是正确性风险**（会产生用户可见 bug）：`tr(default=)` 幻觉参数、仓库 raw 通道根校验空操作、常量双源。
- **4 类是维护性风险**（改一处忘三处的漂移）：仓库三套会话方言、SAVEPOINT 三变体、desktop_ports 双 root 约定、webui 三套 mock 词表。
- **5 类是文档/口径债**：README 数字矛盾（17 vs 12 仓库、Cython 4 vs 8）、`--optimize` 命令不存在、死 E2E spec、`_meta.version` 漂移、icon 计数口径。

统一策略总纲：**新方言 = 已被最多调用方使用、且有测试锁定的那一种**；旧方言全部经棘轮收敛，不用大爆炸重写。推荐批次见 §4；每批次独立可交付、可验证、可中止。

---

## 1. 方言差异全景（12 类，全部实证）

### A. 会话/数据访问方言（最高优先级）

#### D1 · 仓库会话绑定三套方言 ⭐核心

同一个意图——"把仓库绑到活的 LibrarySession、拒绝跨库误用"——存在三份实现：

| 方言 | 实现 | 使用者 | 关键差异 |
|---|---|---|---|
| **新方言**（RootIdentity） | `require_library_session(session)` + `context.root_identity`（RootIdentity.map_key 比较） | tag / collection / metadata / asset_index（4 个） | 会话令牌校验（`core/session_contract.py:21-28` 区分真会话与测试假件）+ `for_session` 严格绑定 + `_bind_session` 四重防错 |
| **旧方言**（duck-typing） | `_session_root(session, name)` 读 `session.root`/`root_str` + `root_identity(root, strict=False)` | share / auth / `_common._CommerceRepository` | **不查会话令牌**；strict=False 不建立进程级所有权（`core/path_resolver.py:96-102` 自认） |
| **自有方言** | `Path(session.root).resolve()` 手工比较 | plugin_metadata（1 个） | 第三份根归一化逻辑 |

- 实证：`share_repository.py:42,146,175-176` vs `tag_repository.py:63,75,112` vs `plugin_metadata_repository.py:43`。
- 连带问题：**6/12 仓库完全没有 for_session**（thumbnail/favorite/gallery_home/revoked_token 仅 raw conn）；raw 通道的 `_path_key` 在 `_library_root is None` 时原样返回路径（`tag_repository.py:203-204`）——绕过根包含性；`_CommerceRepository` 基类（`_common.py:136`）已实现新方言的雏形却只有 free_download_quota 一个使用者。
- **目标方言**：新方言（RootIdentity + require_library_session + `_bind_session` 单向门）。理由：唯一有会话令牌防伪、唯一被 02 号文档确认契约最严的版本。
- **统一路径**：见批次 P1。

#### D2 · SAVEPOINT 三变体 + `_guarded_commit` 分散

同一意图——"仓储写嵌入调用方事务而不截断"——三处实现：

| 变体 | 锚点 | 特点 |
|---|---|---|
| `_common._transaction` | `_common.py:82` | 最简（无失败清理附加诊断） |
| `_write_scope` | tag:217 / collection:201 / metadata:212 | add_note 附加诊断 + require_clean_transaction 选项 |
| `transaction_scope` | asset_index:364 | 外部命名 savepoint + 正则白名单 + **先 BEGIN 再开 SAVEPOINT**（防最外层 RELEASE 直接提交） |

- 最微妙的知识只在 asset_index 变体里（BEGIN-before-SAVEPOINT、白名单）；tag/collection/metadata 变体几乎逐字重复。
- **目标方言**：`_common` 提供唯一 `write_scope()` 上下文管理器（吸收 asset_index 的 BEGIN 语义 + add_note 诊断 + 可选 clean-transaction 断言），各仓库一行调用。

#### D3 · 桌面端口 root 参数双约定

`desktop_ports.py` 同一文件内两种调用约定（自己注释承认，:170-174）：

- `TagsViewPort`：**根绑定，无 library_root 参数**（:23，镜像 TagStoreProtocol）。
- `MetadataViewPort` / `FileOpsViewPort`：**保留 library_root 前导参数**（:169 起），panel 每次调用都传。

- **目标方言**：根绑定（无 root 参数）——因为消费方是 scoped 面板，root 已由 `set_scoped_services` 注入；root 参数退化为一致性检查是历史遗留。统一后 `FileOpsViewPort.last_operation_id` 等接口同步简化。

### B. UI/文案方言

#### D4 · `tr(default=)` 幻觉参数（71 处）⭐正确性

`i18n.tr`（`i18n/__init__.py:36-50`）**不识别 `default`**——kwargs 全部交给 `str.format`，`default=` 是被忽略的死参数；缺键时返回**原始点号键名**（如 UI 上显示 "plugins.select_hint"）。全库 71 处依赖这个不存在的回退（dialogs/panels/widgets 广泛分布，重灾区 plugin_manager_dialog、modal_dialog、command_palette、startup）。
- **目标方言**：`tr()` 增加显式 `default: str | None = None` 参数——缺键时返回 default 而非原始键；71 处调用从"幻觉"变成"真实回退"。这**不改变任何调用点**，只补实现——最低成本的统一。

#### D5 · i18n 缺键回退三套

| 方言 | 位置 | 行为 |
|---|---|---|
| `tr()` 官方 | i18n/__init__.py:46-47 | 缺键 → log warning + 返回原始 key |
| `_msg(key, fallback)` 私有 | dialogs/_sharing_helpers.py:14-23 | **import 私有 `i18n._lookup` 探测** + 英文回退 |
| webui 自带 | webui/src/i18n/index.ts | 缺键 → 回退 en 词典 → 原文 |

- `_msg` 是因为当时 catalog 缺键才生的补丁，D4 落地后**整函数可删**（调用点改 `tr(key, default=...)`）。
- 私有 API 穿透（`_lookup`）一并消除。

#### D6 · 对话框生命周期三套语言刷新

- TabbedDialog：`supports_runtime_refresh=True` 才连 language_changed（settings/tag_editor/plugin_manager 支持）。
- **未声明的对话框**（SharingSettings/UndoPanel/ActivityPanel/ShareLink/ShareQr）：已开窗文案冻结直至重开。
- StartupWindow：完全手写 `refresh_theme/_refresh_language`（startup.py:658-683）——第三套机制。

- **目标方言**：`TabbedDialog` 默认支持语言刷新（`supports_runtime_refresh` 默认 True，个别性能敏感窗显式 opt-out）；StartupWindow 改继承 TabbedDialog 的刷新协议或明确豁免并注释原因。

### C. 装配/调用方言

#### D7 · 挂载清单魔法字符串（无单一事实源）

`for name in ("file_list", "info", "sidebar", "tag_tree")` 在 `window.py:275`（scoped services 注入）与 `window_lifecycle_coordinator.py:214`（prepare_library_switch）两处硬编码；新增面板需要人肉记得两处（或三处，含 shutdown_resources :311 的变体清单）。TYPE_CHECKING 契约（window.py:1605-1618）锁类型但不锁清单。
- **目标方言**：`SCOPED_PANELS: tuple[str, ...] = ("file_list", "info", "sidebar", "tag_tree")` 模块级常量，三处循环引用同一常量；未来加面板改一行。配套静态断言（TYPE_CHECKING 里遍历常量校验属性存在）。

#### D8 · settings 访问双轨

application 层设计了 provider seam（`app_settings_provider.py`，docstring 明言"只有 ApplicationBootstrap 可调用 settings 单例"）——但 `library_governance.py`、`security_preflight.py` 仍直接 `AppSettings.instance()`（panels/widgets 层直连属正常，application 层的直连是违约）。
- **目标方言**：application 层全部经 `get_app_settings()`；新增门禁：`check_boundaries.py` 加一条规则——`AssetsManager/application/` 内除 bootstrap 外禁止 `AppSettings.instance()`（静态扫描，与现有 gate 风格一致）。

#### D9 · `tr` 描述键 vs 字面文案

`ShortcutManager` 的 description 存 i18n key（随语言重译，好范式）；但部分 toast/状态栏文案直接拼英文/中文字面量（grep 可证）。统一为：**一切用户可见文案必须走 tr() + key**——可纳入 check 脚本（检测 `setText("` / `showMessage("` 中的裸非 ASCII 或裸英文句子）。

### D. 跨端与口径方言

#### D10 · webui 三套 mock 词表

Vitest 用 `vi.stubGlobal('fetch')`、E2E 用 `page.route`、contract 用 golden JSON——后端字段改名需三处同步（05 号文档 W-12）。
- **目标方言**：以 `tests/contracts/lan_public_contracts.json`（后端导出的 golden）为**唯一事实源**，三套 mock 从 golden 生成（脚本 `scripts/gen_web_mocks.py`，与 gen_ts_types.py 同模式）。这是方向性规划，投入最大，放最后批次。

#### D11 · 常量双源

- `FavoriteRepository.LIMIT_CEILING=10_000` 刻意复制 `favorite_service.MAX_FAVORITES_PER_OWNER`（注释要求人工同步）。
- `MAX_BATCH_DOWNLOAD_BYTES`（生产常量）在 perf 测试断言一致性（已有守护，好范式）。
- **目标方言**：仓储层 import 服务层常量（或下沉到 core/constants.py），配一条测试断言相等（比注释可靠）。

#### D12 · 文档/口径漂移（影响新人认知）

| 漂移 | 事实 |
|---|---|
| README 架构图"17 个仓库" vs 正文"12 个" | 实测 12 仓库 + `_common` |
| README"Cython 4 个热点模块" | setup_cython.py 列 **8 个** |
| README `build.py --clean --build --optimize --report` | `--optimize` **不存在**，命令会报错 |
| README 测试分域 106/55/54/35 | 实测 114/63/51/63（stats 行 324 是对的，正文漂移） |
| `docs/lan-security.md` seller/shop 路由 | 代码已按 ADR 0005 剥离 |
| webui 三个 commerce E2E spec | 路由已删，spec 是死测试 |
| i18n `_meta.version` en=1 / zh=ja=2 | 无消费无告警 |
| icons"56" | 实测 48 基础 + 10 别名 |

- **目标方言**：正文数字全部改为引用 stats 行（check_doc_stats.py 已守护）或加"以 stats 行为准"脚注；lan-security.md 商城段落移入 archive 标注；死 spec 删除。

---

## 2. 目标方言规范（"唯一写法"清单）

收敛后，每类意图只剩一种写法：

| # | 意图 | 唯一写法 | 锚点（目标实现位置） |
|---|---|---|---|
| 1 | 仓库绑定会话 | `XxxRepository.for_session(session)` → require_library_session + RootIdentity + `_bind_session` 单向门 | `_common.py`（基类重命名 `_SessionBoundRepository`） |
| 2 | 仓库写事务 | `_common.write_scope(conn, prefix, *, require_clean=False, savepoint=None)` 上下文管理器（含 BEGIN 语义 + add_note 诊断） | `_common.py` |
| 3 | 仓库读 | `@locked_read` 装饰器（现有，不变） | `core/database.py:1266` |
| 4 | CAS | 单语句复合条件 UPDATE + rowcount 判定（现有五类模式作为正典示例归档到 `_common` docstring） | — |
| 5 | UI 端口调用 | 根绑定、无 library_root 参数（TagsViewPort 范式） | `desktop_ports.py` |
| 6 | 面板拿服务 | `set_scoped_services(scoped, runtime=runtime)`（ScopedServicesConsumer 契约，不变） | `desktop_ports.py:239` |
| 7 | 挂载清单 | `SCOPED_PANELS` 模块常量 | `window.py` |
| 8 | application 层读设置 | `get_app_settings()` | `app_settings_provider.py` |
| 9 | 用户可见文案 | `tr(key)` / `tr(key, default="…")`（default 真实生效）；缺键警告保留 | `i18n/__init__.py` |
| 10 | 对话框语言刷新 | TabbedDialog 默认支持（opt-out 显式+注释） | `tabbed_dialog.py` |
| 11 | 前后端字段事实源 | golden JSON（contracts.ts + 三套 mock 从此生成） | `scripts/gen_ts_types.py` + 新 gen_web_mocks |
| 12 | 跨层常量 | 单一定义点 + 相等性测试断言 | 按项处理 |

---

## 3. 防回退门禁（每批次随附，缺一不开工）

沿用项目已验证的"棘轮 + 零容忍"门禁模式：

| 方言 | 门禁 | 形态 |
|---|---|---|
| D1 仓库方言 | `check_repository_dialects.py`（新）：`repositories/` 内禁止 `root_identity(strict=False)` 会话路径与 `Path(session.root)` 手工比较；无 for_session 的仓库列入棘轮清单只减不增 | 静态扫描 + ledger |
| D2 SAVEPOINT | 同上脚本：除 `_common` 外禁止裸 `SAVEPOINT` SQL 字符串 | 静态扫描（零容忍） |
| D4/D5 i18n | `check_i18n_defaults.py`（新）：`tr(` 调用若带 `default=` 必须是真实参数（mypy 可查）；`_sharing_helpers._msg` 删除后 grep 零命中 | 单测（tr 行为测试）+ grep |
| D7 挂载清单 | `SCOPED_PANELS` 单测：三处消费点引用同一常量（import 断言） | 单测 |
| D8 settings 违约 | `check_boundaries.py` 增规则：application/ 内除 bootstrap 禁 `AppSettings.instance()` | 现有门禁扩展 |
| D9 裸文案 | check 脚本棘轮：`setText("` 等调用点的裸句子只减不增 | ledger |
| D11 常量双源 | 相等性测试（`assert LIMIT_CEILING == MAX_FAVORITES_PER_OWNER`） | 单测 |
| D12 文档 | `check_doc_stats.py` 已在；补 `check_documents.py` 规则：正文禁止硬编码 stats 行已有的数字（改用引用） | 现有门禁扩展 |

---

## 4. 实施批次（按 投入产出 × 风险 排序）

### P0 · 立即修（✅ 已于 2026-09-04 执行完成，见 §5 证据行）

1. **D4：给 `tr()` 实现 `default` 参数**（i18n/__init__.py:36）+ 5 项行为测试（tests/unit/test_i18n_default.py）。71 处调用点零改动，幻觉变真实。
   - 实施注记：初版签名误用位置限定符 `/`，`default` 落进 `**kwargs` 被 `str.format` 吞掉（这恰是历史 bug 的同款机制）；测试先行暴露后改为普通关键字参数。
2. **D12 部分：删 webui 三个死 commerce spec**（seller/commerce-buyer/commerce-real-backend）+ `.storefront-*` CSS 残迹；README 修正 `--optimize` 命令、"Cython 4→8"、正文分域数字改为 2026-09-04 实测、架构图 17→12 仓库、E2E spec 数 6→3（stats 行经 `check_doc_stats.py --fix` 同步）。
3. **D11：常量双源加相等性测试**（tests/unit/test_favorite_repository.py::test_favorite_limit_constants_stay_in_sync）。
4. 验收：见 §5。

### P0+ · 顺手完成的 P2 快赢项（同日执行）

- **D7（修订版）**：新建 Qt-free 模块 `AssetsManager/window_scoped_panels.py`，定义 **`SWITCH_PANELS`（4 面板）与 `SHUTDOWN_BEFORE_SAVE_PANELS`（3 面板）两个元组**——实施中发现原计划"单一 `SCOPED_PANELS` 替换全部三处"是错的：switch 循环含全部四个面板，而 shutdown_resources 的早期清理循环**刻意不含 file_list**（它在 save.dock/save.tabs 之后单独关闭，见 08 号文档 §4.2 的顺序设计），integration 测试精确锁定该顺序。两个消费点（window.py:283 注入循环、window_lifecycle_coordinator.py:216/313）统一 import。
  - 历史遗留注意：window.py:275 原始注入循环的顺序是 `("file_list", "info", ...)`，与 lifecycle 的 `("info", "file_list", ...)` 顺序本就不同——顺序在两个上下文中均无语义（set_scoped_services 幂等），统一为 SWITCH_PANELS 顺序后测试全绿。
- **D8（核实后关闭）**：深读规划文档所称"library_governance/security_preflight 仍直连 AppSettings"**已过时**——security_preflight.py:398 与 library_governance.py:242 现均已走 `get_app_settings()`，application 层唯一直连是 bootstrap.py:318（设计允许的装配点）。此项无需改动，从 P2 待办中移除。

### P1 · 仓库方言统一（✅ 已于 2026-09-04 执行完成，见 §5 P1 证据行）

1. **重命名并强化基类**（✅）：`_SessionBoundRepository` 落地（`_CommerceRepository` 保留为其别名，free_download_quota 与历史引用不破坏）；吸收四重防错 + `_raw_operation_started` 单向门 + `require_library_session` 令牌校验 + `_write_scope`（SAVEPOINT + add_note 清理诊断）+ **`_apply_root_identity` 钩子**（实施新增：asset_index 的 `_root_identity` 额外状态经此钩子随全部绑定路径发布，修复了"基类直接赋值滞后子类状态"的缺陷）。
2. **迁移 4 个新方言仓库**（✅）：tag/collection/metadata/asset_index 全部删掉逐字重复的 `_session_root`/`_require_session_contract`/`_bind_session`/`_operation_scope`/`_write_scope`（每仓 ~100-160 行）。asset_index 的 `transaction_scope` **保留**（外部命名 savepoint + BEGIN 守卫是其独有契约，relink/asset_index_service 依赖）。
3. **迁移 3 个旧方言仓库**（✅）：share/auth 的 duck-typing `_session_root` 删除、走基类严格方言；plugin_metadata 整仓重写继承基类（自有 Path 比较方言消灭）。**保留的刻意偏差**：tag/collection/metadata/plugin_metadata 的 `_path_key` 覆写保留 raw pass-through（调用方 caller-resolved 路径契约，注释说明）；plugin_metadata 保留 always-resolve 键契约（斜杠变体归一，回归测试锁定）；**基类 `_path_key` 默认对未绑定仓库抛错**（W-5 洞的机制化收口——想用 raw 必须显式覆写声明策略）。
4. **raw 仓库收编**：gallery_home/revoked_token 评估后**暂缓**（各自 54/120 行、单表单职责、无复杂事务，收编收益低于改动面）；thumbnail/favorite 维持 P2 计划。`_path_key` 洞经基类默认拒绝语义收口（见 3）。
5. **随附门禁**（✅）：`scripts/check_repository_dialects.py`——规则：禁本地方言 helper、禁 duck-typed root 探测（代码扫描）、禁裸 SAVEPOINT（白名单外）、绑定模式棘轮（8 strict / 4 raw ledger 只减不增）。**已接入 lint 序列手动跑通，未接入 ci.yml（后续项）**。
6. **测试面更新**（行为增强的诚实对齐）：4 处测试从旧方言断言升级到严格方言——closing-session 绑定测试的 SimpleNamespace fake 经 `register_library_session` 注册 + 补 `context.root_identity`（拒绝语义不变，只是更早更严）；两处错误消息 regex 对齐基类 canonical 文案。
7. 验收：见 §5 P1 证据行。

### P2 · UI/装配方言（✅ 已于 2026-09-04 执行完成，见 §5 P2 证据行）

1. **D6**（✅）：TabbedDialog `supports_runtime_refresh` **默认翻转为 True**（opt-out 须显式声明+注释）；基类 `_on_language_changed` 扩展覆盖 StandardModalDialog 自有按钮行（`_ok_btn/_cancel_btn/_apply_btn` 经 Optional 注解 + None 守卫，pyright 零新增）；modal 基类补 `retranslate_ui`（窗口标题）；**三个高价值活界面补齐 retranslate**——ShareLinkDialog（标题/提示/占位符/过期下拉保序刷新/复选框/四按钮）、ActivityPanelDialog（标题/过滤下拉保序刷新）、SharingSettingsDialog（标题 heading 存为 `_title_label` + 双导航轨按钮）。契约测试 tests/desktop/test_dialog_runtime_refresh.py 5 项锁定默认行为。StartupWindow 维持手写刷新（非 TabbedDialog 子类，QMainWindow，豁免成立）。
2. **D7**（✅ 已在 P0+ 完成，见 §P0+）。
3. **D8**（✅ 已核实关闭：application 层经 provider seam 收敛，规划信息过时）。
4. **D5**（✅）：`_sharing_helpers._msg` 五处调用点全部改为 `tr(key, default=...)`（P0 使 default 成为真实参数）；helper 与 `from AssetsManager.i18n import _lookup` 私有穿透一并删除——i18n 私有 API 引用清零。
5. **D3**（⏸ **评估后后置 P3**）：`MetadataViewPort`/`FileOpsViewPort` 全库**零消费者**（无任何 import——它们当前是自描述文档而非被消费的边界）；且两者 root 参数语义实质不同（Metadata 的 library_root 是 **scope 选择器**——驱动 `_resolve_under_root` 与连接路由；FileOps 的是**可选一致性检查**）。真正的根绑定统一需要改 MetadataService 44 处签名 + info/project_service/info_controller 三消费者，收益不抵改动面，故从 P2 撤出、记入 P3 候选并在此存档判定依据。
6. 验收：desktop 套件 **826 passed**；新增契约测试 5 passed；ruff 全库 All checks passed；pyright 改动文件零新增错误（dialogs/ 21 个全部 pre-existing，per-file 分布与 pristine 完全一致）。切库/切语言手动冒烟未执行（本会话无头环境，建议用户侧一次）。

### P3 · 跨端事实源统一（✅ 已于 2026-09-04 执行完成，见 §5 P3 证据行）

1. **D10**（✅ **以共享 fixture 落地，gen_web_mocks 缓建**）：`webui/e2e/fixtures/lanApiMocks.ts` 成为 E2E mock 唯一词表（`guestPrincipal` + `infoBody(overrides)` 全量 runtime `/api/info` 信封 + `mockGuestWorkspaceApis()` 统一安装 14 条路由），webui-shell 与 a11y 两套 spec 的手写 mock 全部退役。**`gen_web_mocks.py` 生成器评估后缓建**：golden `tests/contracts/lan_public_contracts.json` 的 "info" 是 ServerInfo DTO 子集，**不含** runtime `/api/info` 实际返回的 `principal` 信封——生成器缺少 runtime 形状的超集来源；待后端补出 runtime-shape 契约导出后再建，判定依据在此存档。
2. `lan-security.md`（✅）：头部加剥离标注（ADR 0005，2026-09-04 更新）；三处商城清单条目划线标注"ADR 0005 剥离"；README 路由表删除 `/api/shop/*` 行、`/storefront/*`、`/seller/*` 标注 ADR 0005 剥离（2026-08-30）。
3. i18n `_meta.version`（✅）：en.json 1→2（zh/ja 已为 2；三语各 1059 个叶子 key，精确对齐）；新门禁 `scripts/check_i18n_catalogs.py`（4 规则：平铺 key 方言正则、三语 key 集合一致、`_meta` 卫生 + version 一致、占位符安全——**非英语多出占位符=违规，缺少占位符=合法语言适配**，如英语复数 `{y}`），负例自测通过。
4. **顺带修复（a11y 门禁自身的既有欠账，stash 双重对照确认为 pre-existing）**：
   - shortcuts overlay 断言过期——registry 已 11 条、断言硬编码 10；改为 `toHaveCount(SHORTCUTS.length)` 从 registry 推导（投影完整性由推导保证，不再漂移）。
   - `ProjectList.tsx` "Open" 动作按钮 10px 文本绑 `--color-accent`（dark 4.46:1 < 4.5）——违反 index.css:28 既有治理规则"text usages bind to --color-accent-text"；改绑 `--color-accent-text`（focus ring / hover 背景不变）。
   - 维修后 `npm run build` 重建 dist（Playwright preview 服务预构建产物，源码改动不重建不生效）→ e2e 全套 37/37 绿。

### 不做的事（明确出界）

- 巨石拆分（settings_dialog/reconciliation 三件套/database.py）——架构债，见 `docs/plans/architecture-reliability-roadmap-2026-08-31.md`，不与方言统一混批。
- HTTP 自环（SharingSettingsDialog 打本机 API）——属 port-architecture 计划范畴（`docs/plans/port-architecture-2026-08-30.md`），P2 只做语言刷新不做传输改造。
- webui BrowsePage 巨组件/自研 cache 重构——与 mock 统一无依赖关系，不捆绑。

---

## 5. 每批次交付证据要求（沿用项目证据文化）

按 README 顶部"验证边界"约定，每批次完成时在本文档追加 dated 证据行：

```
P0 · 2026-09-04 · 工作树（未 commit）· 证据：
  · D4 tr(default=) 行为测试 tests/unit/test_i18n_default.py 5 passed
  · D11 favorite 常量测试 tests/unit/test_favorite_repository.py 6 passed
  · D12 webui index.css.test.ts 5 passed；src/api vitest 64 passed (14 files)
  · D7 生命周期回归：test_window_session_switching + test_shutdown_stress
      + test_scoped_service_access + test_window_lifecycle_lan_failure
      → 28 passed, 1 failed（test_main_window_delegates_library_switch_to_lifecycle_coordinator
      为 pre-existing xdist worker crash 0xC0000409——git stash 双重对照在
      pristine 树同样失败，与本批改动无关；单独串行运行时进程级崩溃，
      属 Qt+xdist 环境问题，另立跟踪）
  · ruff check AssetsManager tests scripts run.py → All checks passed
  · pyright（3 个改动模块）→ 0 errors
  · check_doc_stats.py → README stats are current（e2e_specs 6→3、python_test_files 324→325）
  · check_documents.py → document maintenance state is current
```

```
P1 · 2026-09-04 · 工作树（未 commit）· 证据：
  · 基类强化：AssetsManager/repositories/_common.py 落地 _SessionBoundRepository
    （+ _apply_root_identity 钩子；_CommerceRepository 保留别名）
  · 7 仓库迁移：tag/collection/metadata/asset_index/share/auth/plugin_metadata
    继承基类，删除四份逐字重复的绑定脚手架（约 700 行净删）
  · 门禁：scripts/check_repository_dialects.py → "repository dialects are
    current"（8 strict / 4 raw-only 棘轮）
  · ruff check AssetsManager/repositories + scripts → All checks passed
  · pyright AssetsManager/repositories + 门禁脚本 → 0 errors, 0 warnings
  · 靶向回归：test_repositories/test_auth_share_session_binding/
    test_auth_service/test_share_service/test_file_operation_service/
    test_database/test_plugin_metadata_repository_lifecycle/
    test_info_controller → 253+38+22 passed（三批合计全绿）
  · 全套回归 tests/unit + tests/integration → 2705 passed, 6 failed：
      - test_scoped_projection_ordering ×2：pre-existing（git stash 对照 pristine
        树同样失败；测试调用 bootstrap.for_library——该方法在 HEAD 即不存在，
        属陈旧测试断言漂移，非本批改动）
      - ×4（reconciliation/export/import 系列）：单文件隔离复跑全部通过，
        判定为 xdist 并发偶发（含已知 pre-existing worker-crash 环境问题），非本批改动
  · 行为增强：基类 _path_key 默认对未绑定仓库抛错（W-5 洞机制化收口）；
    4 处测试 fake 经 register_library_session 升级到严格方言（拒绝语义不变）
```

```
P2 · 2026-09-04 · 工作树（未 commit）· 证据：
  · D6：supports_runtime_refresh 默认 True（tabbed_dialog.py）+ 基类模态按钮行
    刷新 + 三个对话框 retranslate_ui（share_link/activity_panel/sharing_settings）
    + 契约测试 tests/desktop/test_dialog_runtime_refresh.py 5 passed
  · D5：_sharing_helpers._msg 五处→tr(default=...)；helper 与私有
    i18n._lookup import 删除（grep 清零）
  · D3：评估后置 P3——两个 Protocol 零消费者、root 参数语义实质不同
    （scope 选择器 vs 可选一致性检查），判定依据存档于 §P2-5
  · ruff check AssetsManager tests scripts run.py → All checks passed
  · pyright dialogs/：21 个 pre-existing（per-file 分布与 pristine 完全一致），
    改动文件零新增
  · pytest tests/desktop → 826 passed
  · check_doc_stats --fix → python_test_files 325→326；check_documents → current
  · check_repository_dialects → current（P1 门禁持续绿）
```

```
P3 · 2026-09-04 · 工作树（未 commit）· 证据：
  · i18n：en.json _meta.version 1→2；三语各 1059 叶子 key 对齐；
    check_i18n_catalogs.py → "i18n catalogs are aligned (en=1059, ja=1059,
    zh=1059; _meta.version=[2])"，负例自测通过（4 规则逐条可触发）
  · D10：webui/e2e/fixtures/lanApiMocks.ts 落地（guestPrincipal/infoBody/
    mockGuestWorkspaceApis 14 路由）；webui-shell + a11y 两 spec 手写
    mock 全部退役改接共享 fixture；gen_web_mocks.py 缓建（golden 无
    principal 信封，判定存档于 §P3-1）
  · 文档：lan-security.md 商城三清单划线+ADR 0005 标注；README 路由表
    /api/shop 删除、storefront/seller 标注剥离；check_doc_stats →
    "README stats are current"；check_documents → current
  · e2e：npm run build 重建 dist 后 npx playwright test（app+a11y+shell
    三 spec）→ 37/37 passed（49.1s）；tsc -b exit 0
  · pre-existing 修复（stash 双重对照 pristine 树复现同败，非本批引入）：
    shortcuts 断言 10→SHORTCUTS.length 推导；ProjectList Open 按钮
    text-accent→text-accent-text（4.46:1→5.3:1，dark 过线）
  · vitest run → 95/95 passed（68 个 unhandled error 当时判定为环境 noise——
    该判定在质量轮 Q4 被证伪并修复，见下方质量轮证据行）
  · ruff check AssetsManager tests scripts run.py → All checks passed
  · check_repository_dialects → current（8 strict / 4 raw-only，P1 棘轮持续绿）
```

```
质量轮（Q1–Q4，子代理串行执行）· 2026-09-05 · 工作树（未 commit）· 证据：
  · Q1 测试完整性：test_scoped_projection_ordering ×2 陈旧断言修复
    （bootstrap.for_library → runtime_for(session).services，语义/断言原样）；
    0xC0000409 根因实锤——PySide6 6.11 + Py3.14 下无 QApplication 实例时
    QApplication.setOverrideCursor 静态调用触发 Windows FAST_FAIL（3 行最小
    复现）；测试侧补 QApplication 装配 + overrideCursor 平衡断言；
    ×4 reconciliation/export 偶发 = worker 崩溃连带时序扰动，随崩溃修复消除
  · Q2 pyright 债务清零：全库 157 → 0 errors（search_service 19/window 11/
    file_list 三文件 53/renderer 27/media 9 + 零散 38）；零行为变更（注解/
    None 守卫/cast/类级声明）；desktop 826 passed 稳定
  · Q3 棘轮缩减：favorite_repository 迁移严格方言（SQL 一字未改，9 strict）；
    gallery_home/revoked_token/thumbnail 保持 raw 但三份可审计判定
    （why-raw + revisit 条件）写入模块 docstring；3 raw-only
  · Q4 残留卫生：
    - 两处定时敏感偶发治本（gallery 投影改轮询 DB 行、thumbnail 锁测试
      冷启动窗口 2.0s→20s deadline 循环），单跑 ×3 + 全套通过
    - vitest 68 error 根因证伪并修复：Vite 7.3.6 Windows 对含 '~' 路径的
      isFileLoadingAllowed 硬拒绝 → 68 个 jsdom 测试文件从未真正运行
      （"95/95 全过"实为 21 个 node 文件）；vite.config.ts tildePathLoader
      插件（保留驱动器冒号/真实文件两安全检查）→ 665/665 全绿 0 error，
      e2e build 不受影响；新基线 665（此前 570 个测试从未被检验）
    - commerce 残留扫描：活代码零违规；唯一清理 system.py:26 过时注释
    - i18n 死 key 外科删除 24 个三语同步（sharemgr.col 6/sharing.quick 8/
      sharing.settings 10）→ 1035×3；~85 个低置信度疑似 key 保留待运行时
      覆盖深审；附带修复 test_route_capabilities 的 Settings stub 4 方法
  · 终验：pyright 0；ruff All checks passed；vitest 665/665 0 error（×3）；
    tsc -b exit 0；e2e build 后 37/37 passed（55.4s）；
    check_i18n_catalogs → aligned（1035×3, version=[2]）；
    check_repository_dialects → current（9 strict / 3 raw-only）；
    全套 Python（unit+integration+desktop）双跑稳定：
    3539 passed, 17 skipped, 0 failed（111s/121s 两轮）；
    check_doc_stats --fix（i18n_en 1060→1036）+ check_documents → current
```

无证据即 unverified——本文档自身也是这个纪律的适用对象。

---

## 6. 依赖关系图

```
P0(D4 default 实现) ──► P2-4(D5 删 _msg)
P1(基类下沉)        ──► P2(无依赖，可并行)
P2(D3 端口根绑定)    ──► 与 03 号文档 desktop_ports 消费面联动
P0(D12 文档修正)     ──► deep-analysis README §2 漂移表勾选
D10(gen_web_mocks)   ──► 独立，但建议在 P1/P2 稳定后启动
```

---

## 附录 A · 71 处 `tr(default=)` 分布（grep 实测）

plugin_manager_dialog.py（7）、modal_dialog.py（3）、empty.py（1）、command_palette.py（多）、startup.py（2）、plugin_ui.py（1）、settings_dialog.py（1）等——完整清单见 `grep -rn "default=" AssetsManager --include="*.py" | grep "tr("` 输出（71 行）。

## 附录 B · 仓库方言迁移映射表

| 仓库 | 现方言 | 目标 | 批次 |
|---|---|---|---|
| tag / collection / metadata / asset_index | 新方言（自有样板） | 继承 `_SessionBoundRepository`（删样板） | P1-2 |
| share / auth | 旧方言（duck-typing） | require_library_session + RootIdentity | P1-3 |
| plugin_metadata | 自有方言（Path 比较） | 同上（保留轻量校验） | P1-3 |
| free_download_quota | 继承 _CommerceRepository | 改名继承（零行为变化） | P1-1 |
| gallery_home / revoked_token | 无绑定（raw） | for_session + 根绑定 | P1-4 |
| thumbnail / favorite | 无绑定（raw） | for_session + 根绑定（thumbnail 牵 v2/v3 键，谨慎） | P2/后续 |

## 附录 C · 目标基类签名草案

```python
class _SessionBoundRepository:
    """唯一仓库基类：会话令牌 + RootIdentity + 写事务上下文。

    迁移自 tag_repository 的 _bind_session 四重防错与 _write_scope
    （吸收 asset_index 的 BEGIN-before-SAVEPOINT 语义）。
    """
    def for_session(cls, session, *, library_root=None) -> "Self": ...
    # raw 单向门：首次 raw 操作后永久关闭会话绑定通道（不变）
    # _path_key：_library_root is None 时拒绝（新行为，P1-4）
```

## 附录 D · 记录在案但不属于"方言"的架构债

巨石模块（reconciliation 2733 行等）、HTTP 自环、`__init__.py` 全量 re-export、webui 自研 query cache 复杂度——见 `docs/deep-analysis-2026-09-04/` 各文档弱点清单；治理归 architecture-reliability-roadmap。
