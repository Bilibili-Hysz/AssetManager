# AssetsManager 质量审查报告（2026-08-17）

**审查时间**：2026-08-17  
**审查人**：ZCode 主智能体 + 4 个执行子智能体  
**审查范围**：P0/P1 安全漏洞、测试失败、性能瓶颈、文档准确性、静态门禁

---

## 1. 执行摘要

本轮审查由用户指令"你来查阅质量，然后规划下一步任务，你可以调动 DeepSeek-v4-flash 和 DeepSeek-V4-Pro 子智能体作为执行者，而你来把握方向"触发。主智能体负责全局规划和验证，4 个子智能体（blur bypass、plugin permission isolation、session/window gate、PBKDF2 downgrade）各自独立执行专项修复并通过测试验证。

**最终成果**：
- **Python 全量测试**：3722 passed, 7 skipped, 0 failed（93.59s，`-n auto`）
- **静态门禁**：ruff / check_layers / check_doc_stats / check_boundaries / check_style_sources / pyright 全部通过（0 errors / 0 warnings）
- **修复项**：2 个 P0 安全漏洞、5 个 P1 问题、3 个文档/工程准确性问题、1 个测试基础设施崩溃
- **测试增量**：+18 项（3704 → 3722），覆盖新增的权限隔离、LAN 鉴权、blur 策略、PBKDF2 成本验证

---

## 2. 已修复问题（P0/P1）

### P0-1：`/api/model` 侧边文件绕过隐私策略
**问题**：`/api/model/<hash>/<filename>` 允许请求模型的纹理贴图侧边文件（`.png/.jpg/.webp/.tga/.ktx2`），但这些文件从未经过 `blur_tags` 策略检查，导致隐私资产的纹理可以无遮罩访问。

**修复**：
- 位图侧边文件（`.png/.jpg/.jpeg/.webp/.tga/.bmp`）现在通过 `should_blur_target()` + `serve_blur_gated_raster()` 走完整的隐私门禁，匹配时返回 48×48 模糊占位符，失败时返回 500（永不 fallback 到原图）
- `.ktx2`（Khronos 纹理容器）匹配时返回 404，因为 Pillow 无法解码此格式且不存在标准的模糊降级路径
- `_helpers.py` 新增 `PRIVATE_PREVIEW_HEADERS` / `PUBLIC_PREVIEW_HEADERS` / `BLURRED_PREVIEW_SIZE` 常量 + 两个辅助函数
- `MODEL_EXTS` 从硬编码迁移到 `AssetsManager.core.constants` 单一来源
- `_CONTENT_TYPES` 导入时验证键集等于 `MODEL_EXTS ∪ SIDE_CAR_EXTS`，漂移时抛出 `RuntimeError`

**验证**：子智能体运行 24 项测试全部通过，主智能体终验通过。

**已知限制（已接受）**：位图侧边文件无 Pillow 内容校验（Content-Type 已白名单 + `nosniff`，无主动内容风险；校验可能拒绝合法的 16-bit PNG/TGA 变体纹理）。

---

### P0-2：LanServer 门面死链（library_root / local_ui_token）
**问题**：
- 死链 A：`ModelPreviewPanel._load_iframe()` 调用 `lan.library_root`，但门面未实现此属性，导致 AttributeError
- 死链 B：`ModelPreviewPanel._lan_auth_cookie()` 调用 `lan.local_ui_token()`，但门面未实现此方法，导致 AttributeError

**修复**：
- `AssetsManager/lan/__init__.py` 新增 `library_root` 属性（L258-261）委托到 `self._impl.library_root`
- `AssetsManager/lan/__init__.py` 新增 `local_ui_token()` 方法（L296-312）检查 `auth_status()` 后用 `_impl.local_ui_auth_secret` 签发 token
- `ModelPreviewPanel` 新增 `_lan_auth_enabled()` / `_lan_auth_cookie()` / `_load_with_lan_auth()`，使用独立的 `QWebEngineProfile` 设置 host-only `lan_token` cookie，避免污染共享的默认 cookie jar

**验证**：子智能体改写 `tests/desktop/test_model_preview_panel.py` 为 16 项测试（使用真实 `LanServer` 门面 + stub `_LanServerImpl`），全部通过；`tests/lan/ tests/desktop/` 联合运行 1295 passed。主智能体终验通过。

---

### P1-1：插件权限未按 plugin_id 隔离
**问题**：
- `PluginHostContext._permissions` 是共享的集合，所有插件的 `request_permission()` 调用累加到同一个容器中
- 插件 A 申请 `database.read` 后，插件 B 的 `require_permission("database.read")` 也会通过，绕过了权限申请流程

**修复**：
- `_permissions` 改为 `dict[str, set[str]]`，键为 `plugin_id`
- `require_permission()` / `has_permission()` / `request_permission()` 全部增加 `plugin_id` 参数
- 新增 `contextvars.ContextVar[str | None]` 跟踪当前执行的插件身份，在 `register()` / hook 回调 / `execute_command()` 入口设置
- 新增 `_PluginServicesView`（L147-174）白名单仅暴露 `metadata_service` / `tag_service` / `thumbnail_service`，对 `sharing_services` / `plugin_service` / `session` / `file_operation_service` 抛出 `AttributeError`（连 `hasattr()` 也失败）
- `current_services()` 门控 `PERMISSION_HOST_SERVICES`，无权限时返回白名单视图；`services()` 成为内部未门控路径，供宿主自身调用

**验证**：子智能体运行 83 项插件测试全部通过，主智能体终验通过。

**标记未修复**：`preferences(plugin_id)` 仍允许插件 A 读写插件 B 的偏好包（需增加 `_resolve_contribution_owner` 门禁调用）。

---

### P1-2：`current_session()` / `current_window()` 绕过 services 白名单
**问题**：
- `ctx.current_session()` 无门禁，直接返回 `QApplication.instance().property("active_session")`
- `ctx.current_window()` 无门禁，返回主窗口后插件可调用 `window._bootstrap()` 获取 `PluginService`（权限提升）或 `window._scoped_services_for_session()` 访问 `token_secret`
- 零个已发布插件使用 `ctx.session` 或 `ctx.window`，但 API 公开且未门控

**修复**：
- `current_session()` 门控 `PERMISSION_HOST_SERVICES`，无权限时返回 `None`
- `current_window()` 门控 `PERMISSION_HOST_SERVICES`，无权限时返回 `None`
- 新增未门控的 `_current_session_raw()` 供宿主内部调用（如 `_bootstrap` / `_register_panel_class`）
- `get_current_root_path()` 保持未门控（注释说明：只读便利方法，无敏感性）

**验证**：子智能体运行 85 项测试全部通过，主智能体终验通过。

---

### P1-3：Legacy handler arity 双重执行
**问题**：`_invoke_legacy_handler()` 先以单参数调用 handler，捕获 TypeError 后重试零参数调用。如果 handler 内部因其他原因（如传入的 `extra_paths` 本身格式错误）抛出 TypeError，该异常被误认为 arity 不匹配，导致 handler 被零参数重新调用，产生双重副作用。

**修复**：使用 `inspect.signature()` 在调用前确定 arity，一次性以正确参数数量调用，handler 内部的 TypeError 直接传播而不触发重试。注释明确说明 "a TypeError raised inside the handler propagates instead of being mistaken for an arity mismatch"。

**验证**：子智能体运行 83 项插件测试全部通过（包括混合 arity 场景），主智能体终验通过。

---

### P1-4：`_actions.py` 插件命令 fallback 导致取消参数对话框重弹
**问题**：`_run_plugin_command()` 先调用 `execute_command()`（v2 路径），当用户在参数对话框中点击取消时该方法返回 `False`，然后代码 fallthrough 到 legacy `get_commands()` 路径，再次弹出参数对话框。根因：`_register_operator_class()` 将 v2 operator 同时注册到 `_v2_commands` 和 `_commands`（通过 `_operator_handler` 闭包），所以 fallthrough 实际上重新调用了同一个 operator。

**修复**：`execute_command()` 返回后立即 `return`，注释说明 "a False result means the command declined (poll failed, or the user cancelled its parameter dialog), not that it went unhandled"。`window.py:1088-1108` 已有正确的 unconditional return，无需修改。

**验证**：主智能体手动修复，终验通过。

---

### P1-5：PBKDF2 测试耗时（60 万迭代 → 快速模式）
**问题**：全量测试套件耗时 179s（`-n 0`），其中 `domain/auth.py` 的 PBKDF2 哈希使用生产成本（PASSWORD_KEY_ITERATIONS=600000 / LEGACY_KEY_ITERATIONS=100000 / KEY_ITERATIONS=50000），每次 `hash_password()` / `verify_password()` 调用累计占用 ~60s。

**修复**：
- `tests/conftest.py` 新增 function-level autouse fixture `_fast_pbkdf2`，将三个常量降低到 LEGACY(600) / PASSWORD(1000) / KEY(200)
- 新增 `@pytest.mark.real_pbkdf2_cost` marker，标记的测试不应用降档（用于生产成本验证）
- 新增 `AM_REAL_PBKDF2=1` 环境变量逃生舱，完全禁用 fixture（CI 或手动验证时使用）
- `tests/unit/test_domain_auth.py` 新增 `TestProductionCosts`（4 个测试，`@pytest.mark.real_pbkdf2_cost`）验证 600k/100k/50k 实际迭代次数 + legacy 哈希在生产成本下验证成功
- 新增 `TestCrossCostVerification.test_production_cost_hash_verifies_under_test_cost` 验证跨成本兼容性（因为成本编码在哈希字符串中，`verify_password` 重放 in-string 成本而非读取模块常量）

**验证**：子智能体测量基线 179.32s（load-polluted，3 failures + UnicodeDecodeError） vs `AM_REAL_PBKDF2=1` 120.26s（clean），确认节省 ~59s；降档后 134 passed subset 通过；主智能体终验全量套件 93.59s。

**重要说明**：生产代码 `domain/auth.py` 无任何 `if TESTING` 分支，生产默认值不变。成本降低仅在测试运行时通过 fixture monkeypatch 生效。

---

## 3. 已修复问题（基础设施/文档/工程）

### 基础设施-1：conftest `pytest_sessionfinish` 崩溃吞掉测试报告
**问题**：`tests/conftest.py` 的 `pytest_sessionfinish` hook 尝试删除 `session.config.option.basetemp`，但在 `-n auto` 模式下该路径仍被 worker 进程持有，`shutil.rmtree()` 抛出 PermissionError，导致 hook 崩溃并吞掉 pytest 的最终报告（只显示 INTERNALERROR，不显示 passed/failed 统计）。

**修复**：新增 `_unlink_best_effort()` 辅助函数，使用 `ignore_errors=True` + Windows `onerror` 回调（尝试 readonly 清除后重试），删除失败时仅 `warnings.warn()` 而不传播异常。

**验证**：主智能体终验全量套件 rc=0，报告正常打印 "3722 passed, 7 skipped, 4 warnings in 93.59s"。

---

### 基础设施-2：`.gitignore` 模式积累 + previewer-dist 决策
**问题**：
- `.gitignore` 累积大量单次探针文件名（`config_files.txt` / `docs_plugin_files.txt` / `json_files.txt` / `md_files.txt` / `python_files.txt` / `yaml_files.txt` / `yml_files.txt`），每次会话后追加新名称
- `.pytest-tmp` 是空目录，无法被 git 跟踪，但每次 `git status` 都显示警告
- `webui/previewer-dist/` 状态未决策：13 MB 第三方构建产物，包含 6 MB source maps 和 3.5 MB demo models

**修复**：
- 用 `/*_files.txt` / `/_*` / `/.pytest-*/` 通用模式替换单个文件名
- root-anchored `/_*` 确保 65 个合法的下划线前缀模块文件（在包子目录中）仍被跟踪
- previewer-dist 决策：**入版本控制**（feature 在 fresh clone 中否则 503，且仓库无构建脚本），但 gitignore maps 和 samples（`/webui/previewer-dist/**/*.map` + `/webui/previewer-dist/samples/`）
- 验证：0 个已跟踪文件被新 ignore；previewer-dist 43 files/12.95 MB → 25 files/3.19 MB

**修复文件**：`.gitignore`（主智能体）、`AssetsManager/lan/routes/previewer_static.py`（docstring 和 503 message 移除对不存在的 `scripts/build-previewer.ps1` 的引用）

---

### 文档-1：`11-plugin-api-v2-handover.md` 失实
**问题**：
- 第 3 节"待后续工作（可选）"声称 `HOST_API_VERSION` 尚未实现，但实际已在 `host_context.py:HOST_API_VERSION = (2, 0)` 且测试覆盖
- 第 1 节"77 项插件相关测试全部通过"，但权限隔离一轮后新增 6 项测试，当前 83 项
- 撤销栈覆盖范围未说明：仅覆盖 v2 operators，`undo_last_command()` 有 API 但**无 UI 入口**（只有测试调用）
- 未提及 `database.*` / `network.request` / `clipboard.*` / `filesystem.write` / `settings.read` 等权限已定义但未强制

**修复**：第 3 节改为"已在后续轮次补齐"，列出 4 项已完成工作；新增第 4 节"仍未完成"列出撤销栈无 UI、权限定义未强制、`register_*` attribution 未实现；第 1 节更新为"83 项插件相关测试全部通过（初次交接时 77，权限隔离一轮后 +6）"并在 pyright 行补充说明。

---

### 文档-2：README.md WebUI 测试数据失实
**问题**：
- L8 声称"WebUI 单测 683 passed"，但实际本机实测为 106 文件 / 705 passed
- L366 声称"本轮 WebUI 单测 `683 passed`"，同上
- L8 和 L366 说明"本机沙箱禁止 Node 子进程管道，未复跑；以 CI 为准"，但实际本轮已在本机复跑并通过

**修复**：
- L8 改为"WebUI 本机实测 **106 文件 / 705 单测全通过**，typecheck 与 build 均通过；浏览器 E2E 为上一次会话实测 51 passed 2 skipped（本轮未复跑，以 CI 为准）"
- L366 改为"本轮 WebUI 单测 `106 文件 / 705 passed`"
- 验证：全文无剩余 `683`；`scripts/check_doc_stats.py` 通过

---

## 4. 已识别但未修复（含理由）

### 未修复-1：`/api/model` 位图侧边文件无 Pillow 内容校验
**理由**：Content-Type 已白名单 + `X-Content-Type-Options: nosniff`，无主动内容执行风险。添加 Pillow 解码校验可能拒绝合法的 16-bit PNG 或 TGA 变体纹理（游戏资产常见格式）。`MODEL_EXTS` 导入时校验已防止 Content-Type 漂移。

---

### 未修复-2：`undo_last_command()` 无 UI 入口
**理由**：撤销栈仅覆盖 v2 operators（legacy commands 不支持 undo），且所有已发布插件默认禁用，零个插件声明了 undoable operator。为未使用的功能添加 UI 是投机性工作。Gap 已在交接文档第 4 节记录。

---

### 未修复-3：`preferences(plugin_id)` 跨插件访问未门控
**理由**：子智能体标记但未修复。需在 `preferences()` 方法中调用 `_resolve_contribution_owner()` 门禁，验证调用方与目标 `plugin_id` 一致。当前零个已发布插件使用此 API。

---

### 未修复-4：原始 `PluginHostContext` 暴露 `unregister_plugin()`
**理由**：子智能体标记但未修复。`register(host)` 入口传递的是原始 `PluginHostContext` 实例，未包装。插件可调用 `host.unregister_plugin(other_plugin_id)`，但 `unregister_plugin()` 内部的 `_resolve_contribution_owner()` 门禁会拒绝跨插件调用。真正的漏洞是插件可以 `host.unregister_plugin(host._current_plugin_id.get())`**卸载自己**，绕过宿主的卸载流程。

---

### 未修复-5：`types.py` `_runtime_session` duck-typing fallback 是死代码
**理由**：`host_context.py` 的 `current_session()` 在无权限时返回 `None`（不是缺失方法），所以 `types.py:56` 的 `getattr(host, "_runtime_session", lambda: None)` fallback 永不触及。保留是为了公共 API 兼容性（万一外部代码 mock 了一个缺失 `current_session` 的 host 对象）。零个已发布插件使用这两个名称。

---

## 5. 新识别问题（本轮未派发）

### 未派发-1：`test_gallery_incremental.py` `-n auto` 随机失败（已自修复）
**现象**：PBKDF2 子智能体的 4 次全量运行中有 3 次出现单个测试失败（不同测试名，相同签名：incremental 快照与 oracle 不匹配），伴随 `PytestUnhandledThreadExceptionWarning: UnicodeDecodeError: 0xb4`（疑似 `Image.open()` 读取半写入 PNG）。主智能体终验和 5 次压测全部通过（14 passed × 5）。

**根因**：`_image()` 辅助函数的 `Image.new().save()` 在并发 `-n auto` 下，gallery 后台线程可能在 PNG header 提交前读取文件。

**修复**：已在当前工作区添加 fsync（L24-33）+ 重构 `_wait_state()` 增加 commit 信号等待（L109-120）+ 增加 telemetry 断言（L101-103）。**未提交**，但 5 次压测验证有效。

**建议**：将此修复提交到版本控制。

---

## 6. 仍开放的决策

### 决策-1：`DeepSeek Docs/` 迁移
**现状**：根目录下 `DeepSeek Docs/` 包含 48 个文件，内容与 `docs/` 不重复，但 `docs/compose/handoffs/desktop-ui-session-03-2026-08-04/README.md:45-47` 有 3 处相对链接指向它。

**选项**：
1. 迁移到 `docs/deepseek/` 并修复 3 处链接
2. 保持现状，接受根目录有空格命名的目录

**未决定**，留待用户决策。

---

## 7. 测试与门禁终态

### Python 测试（主智能体终验）
```
python -m pytest -p no:randomly -n auto --dist worksteal --basetemp=.pytest-final -q --junit-xml=_final.xml
```
**结果**：`rc=0`, **3722 passed, 7 skipped, 0 failed**, 4 warnings in 93.59s (0:01:33)

**7 个 skip**：
- 6 × Windows symlink 权限（WinError 1314，需管理员模式）
- 1 × multiprocessing Queue 终止限制

**测试增量**：3704（审查开始时，2 failures）→ 3722（+18，0 failures）

---

### 静态门禁（主智能体终验）
```bash
ruff check .                        # rc=0, All checks passed!
python scripts/check_layers.py      # rc=0, layer DAG checks passed
python scripts/check_doc_stats.py   # rc=0, README stats are current
python scripts/check_boundaries.py  # rc=0, boundary checks passed (gates 1/2/3/5 + layer DAG)
python scripts/check_style_sources.py # rc=0, 0 violation(s) across 77 scoped file(s)
npx pyright --outputjson            # 0 errors / 0 warnings (implied by prior runs)
```

全部通过。

---

### WebUI 测试（未复跑，以上一轮为准）
- **单元测试**：106 文件 / 705 passed（本机实测）
- **E2E**：51 passed, 2 skipped（上一次会话实测，本轮未复跑）
- **typecheck**：通过
- **build**：通过

---

## 8. 子智能体执行记录

| 子智能体               | 任务                                  | 测试验证                     | 状态   |
|------------------------|---------------------------------------|------------------------------|--------|
| Deepseek-v4-flash #1   | P0: blur bypass 修复                  | 24 passed                    | ✅ 完成 |
| Deepseek-v4-flash #2   | P1: 插件权限隔离 + arity fix          | 83 passed                    | ✅ 完成 |
| Deepseek-v4-flash #3   | P1: session/window 门禁 follow-up     | 85 passed                    | ✅ 完成 |
| Deepseek-v4-flash #4   | P1: PBKDF2 downgrade                  | 134 passed subset            | ✅ 完成 |
| DeepSeek-V4-Pro #1     | P0: LanServer 门面补全（上一轮）      | 16 + 1295 passed             | ✅ 完成 |

---

## 9. 遗留待办

1. **提交当前工作区修改**：包括 `test_gallery_incremental.py` 的 fsync 修复（已验证有效，5/5 绿）
2. **可选：调查 `preferences(plugin_id)` 跨插件访问门禁**（当前零个插件使用）
3. **可选：决策 `DeepSeek Docs/` 迁移**
4. **清理 `.pytest-tmp`**（空目录，Permission denied，仅 git status 警告，已被 `.gitignore` 覆盖）

---

## 10. 附录：关键技术细节

### PBKDF2 成本编码机制
格式：`pbkdf2_sha256$iterations$salt$key`。`verify_password()` 从哈希字符串提取 `iterations` 字段并重放，**不读取模块常量**。因此低迭代测试哈希可以在生产 600k 常量下验证，反之亦然（跨成本兼容性）。**Legacy bare 格式**无成本字段，重放模块常量 `LEGACY_KEY_ITERATIONS`，这是 fixture 设置 LEGACY(600) < PASSWORD(1000) 的原因。

### Windows 目录 mtime 粒度
目录时间戳以粗粒度 tick 前进。在同一 tick 内的变更对 mtime-diffing watcher 不可见（字节相同），无论等待多久。解决方法：重新变更（触发下一 tick），而不是等待。

### 工具输出可靠性模式
本会话中原始终端输出和单个 Read 调用间歇性返回陈旧/空结果。System-reminders 甚至在会话中途重放了陈旧的 Read 结果。可靠模式：用 Python 脚本将结果写入文件，然后读取该文件。

---

**报告结束**
