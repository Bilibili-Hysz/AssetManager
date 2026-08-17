# AssetsManager 插件 API v2 交接文档

**最后更新**：2026-08-17（本轮审计结束）  
**维护人**：ZCode

---

## 1. 工作完成度

✅ Operator 参数收集 + 对话框 + 撤销栈  
✅ PanelContributor 挂到 MainWindow dock  
✅ download_tracker 迁到 v2 示例（Preferences + EventHook + FileParser + 面板）  
✅ 插件定向测试 205 passed（权限隔离 + 线程洗白修复后）  
✅ 全量测试 3748 passed, 7 skipped（环境限制）  
✅ ruff + 分层门禁 + pyright 252 files 0/0 通过  

---

## 2. 当前架构状态

**插件系统 v2 核心已完成**：
- `register_class` + MRO 分派（单源、易扩展）
- live `PluginContext`（getter 风格，Blender `bpy.context` 模式）
- 参数提示 + `set_param_prompt` + 撤销栈
- `PanelContributor.area` + dock 传入 widget
- `download_tracker` 迁到 v2 示例（Preferences + EventHook + FileParser + 面板）
- 所有贡献类均在 `AssetsManager.plugin_api` 暴露

**插件仍关闭状态**，不影响 booth_link 旧插件。

---

## 3. 权限与身份隔离（2026-08-17 最终状态）

**本轮已关闭的安全缺陷**：

1. **线程绕过权限门**（已修复，+5 测试）：`_check_permission_warn()` 的空 subject 从「免检放行」改为拒绝。此前插件可把 `register_file_handler` / `register_category` / `register_search_provider` / `register_theme_token` / `open_path` 五个 API 挪进 `threading.Thread` 绕过检查（Python 3.14 线程默认不继承 ContextVar）。修复：空 subject 记 WARNING 并拒绝；宿主管理路径显式进入 `_host_identity_scope(_registering_plugin_var, plugin_id)`。

2. **线程洗白提权**（已修复，+6 测试）：插件在新线程里调 `grant_permissions('self', {'host.services'})` 能自授权（实测复现），拿到 `host.services` = 拿到整个服务束。`unregister_plugin` 同样可洗白。修复：引入**显式宿主身份标记**（`_host_identity_var: ContextVar[bool]` + `_host_identity()` 上下文管理器），让「宿主」不再等同于「没设过 ContextVar」；`grant_permissions` / `unregister_plugin` 改为三态闸门（有插件 subject 拒绝、无 subject 无宿主标记拒绝、无 subject + 宿主标记放行）；`manager.py` 三处调用点包上 `_host_identity()`。51 处现有测试调用按角色包身份，未改任何断言值。

3. **跨插件枚举信息泄露**（已修复，同上）：`granted_permissions(plugin_id)` 接受任意 id。修复：插件 subject 只能读自己的，传他人 id 记 WARNING 并返回自己的集合；无插件 subject 时可查任意插件（plugin_manager_dialog 需要，且仅信息泄露无能力增益）。

**早期轮次已完成**：
- 权限从 warn 改为强制拦截，按 `plugin_id` 隔离记账（此前所有插件共享一个集合）
- `PluginContext.services()` 加 `host.services` 门 + 白名单视图（`sharing_services` 内含 LAN token secret、`plugin_service` 可提权、`session` 含数据库连接，均不对插件可见）
- `PluginContext.session()` / `PluginContext.window()` 加 `host.services` 门（`window._bootstrap` → `PluginService`、`window._scoped_services_for_session` → token secret 是提权路径）
- 冒充门：公开 `plugin_execution()` / `plugin_registration()` 在已有 subject 时拒绝切换到不同 id（保持原身份不变，记 WARNING）；宿主合法换身份场景改用私有 `_host_identity_scope`（11 处）
- 身份门：`execute_command()` / `undo_last_command()` 只允许插件操作自己的命令
- Manager host 绑定生命周期：换 host 加载拒绝、`load_plugin(pid, None)` 保留旧绑定、最后卸载后自动清空
- Legacy handler arity 修复：改用 `inspect.signature`，handler 内部 TypeError 不再被误判为参数不匹配而重跑

**十个权限 token 的真实语义**（按"真实边界 / advisory / 无执行点"三档）：

- **真实边界**（能力只能经主机 API 到达）：
  - `host.services` — `current_services()` / `current_session()` / `current_window()` 缺权限返回 None，服务束与库会话无第二路径；**数据库访问打包在此**
  - `settings.write` — `register_category()` / `register_theme_token()` 修改全局注册表，缺权限拒绝

- **advisory 门**（主机 API 有门，插件可用标准库直通）：
  - `filesystem.read` — 门禁 `register_file_handler()` / `register_search_provider()` / `open_path()`，只控制"谁被喂路径"；插件可 `open()` 直读
  - `settings.read` / `settings.write` — 门禁 `preferences()`；插件可直接 `import` 构造 bag 绕过

- **无执行点**（主机无对应 API 可门禁）：
  - `filesystem.write` / `network.request` / `clipboard.*` — 主机不代写文件、不做网络请求、不管剪贴板
  - `database.*` — 唯一入口 `current_session()` 已被 `host.services` 拦截

**根本性边界**：插件与主机同解释器运行、无沙箱——以上任何门禁（含 `host.services`）都能被插件 `import` 标准库或主机模块直接绕过；这是诚实/意图边界而非安全边界。要真隔离需子进程。

## 4. 确认暂不修复的项

- **撤销栈仅覆盖 v2 operator**（`undoable = True` 的 `CommandOperator`），legacy handler 不进栈；`undo_last_command()` 已实现但**无 UI 入口**，只有测试调用。原因：v2 插件当前关闭状态，无任何已装插件声明 undoable operator，接一个没有数据流经的入口是投机实现。
- **进程内诚实边界**：插件可直接调 `_host_identity()` 或改写 `_executing_plugin_var` / `_permissions_by_plugin` 绕过门禁。同解释器内无法防御，要真隔离需子进程。文档已如实标注。

## 5. 剩余收尾项（进入桌面端优化前）

以下项目需在「收尾插件系统 V2 规范」阶段完成：

1. **快捷键冲突检测**：多个 operator 声明同一 `shortcut` 时无告警，后注册的会覆盖。需在 `register_command` 检测并记 WARNING。
2. **设置页 Plugins Tab**：当前插件管理只能通过菜单 Tools → Plugin Manager 对话框，无嵌入设置页的面板。
3. **v2 插件示例文档**：`download_tracker` 已迁到 v2，但无配套的「如何编写 v2 插件」教程文档（与 v1 legacy 对照的迁移指南）。
4. **manifest schema 验证**：`plugin.json` 当前只做字段访问，无 JSON Schema 校验；格式错误的 manifest 会在运行时抛异常而非加载时拒绝。

以上项均不影响核心功能，但影响开发者体验和系统完整性。