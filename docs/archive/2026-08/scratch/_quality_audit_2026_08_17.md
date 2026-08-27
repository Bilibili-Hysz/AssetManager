# AssetsManager 质量审查报告

**审查日期**：2026-08-17  
**审查人**：ZCode（tm-token/claude-opus-5）  
**审查范围**：全量 Python 测试套件 + 5 项静态门禁 + 4 轮子智能体派遣

---

## 1. 执行摘要

### 1.1 测试套件状态

```
Python 全量：3722 passed, 7 skipped, 0 failed in 93.59s
测试增长：  3704 (审查前) → 3722 (当前), +18 from 4 subagent dispatches
7 个 skip： 6 × Windows symlink 权限 (WinError 1314) + 1 × multiprocessing Queue 终止
```

### 1.2 静态门禁状态

| 门禁 | 状态 | 备注 |
|------|------|------|
| `ruff check .` | ✅ All checks passed | correctness 规则族 |
| `check_layers.py` | ✅ layer DAG checks passed | AST 静态强制 |
| `check_doc_stats.py` | ✅ README stats are current | 统计同步 |
| `check_boundaries.py` | ✅ gates 1/2/3/5 + layer DAG | 边界检查 |
| `check_style_sources.py` | ✅ 0 violations (77 files) | 样式源一致性 |
| `pyright` | ✅ 0 errors / 0 warnings | CI 固定 1.1.410 |

---

## 2. 已派遣并完成的工作（5 项）

### 2.1 P0：/api/model 侧车图片绕过 blur 策略

**执行者**：DeepSeek-v4-flash  
**验证**：24 passed, pyright 0/0

**变更**：
- `model_preview.py`：位图侧车（.png/.jpg/.jpeg/.webp/.tga/.bmp）走 `should_blur_target` + `serve_blur_gated_raster`
- `.ktx2` 无 Pillow 解码器时返回 404（隐私不变式：处理失败不回退原图）
- `_helpers.py`：新增 `should_blur_target(request, target)` 和 `serve_blur_gated_raster()` 中心化隐私逻辑
- `thumbnail_service.py`：公开 `check_blur()` 方法供路由直接调用

### 2.2 P0：LanServer 门面补全（死链 A/B）

**执行者**：DeepSeek-V4-Pro  
**验证**：16 passed (model_preview_panel.py), 1295 passed (tests/lan/ + tests/desktop/)

**变更**：
- `lan/__init__.py`：新增 `library_root` 属性委托到 `_impl.library_root`
- `lan/__init__.py`：新增 `local_ui_token()` 方法检查 auth 状态后用 `_impl.local_ui_auth_secret` 签发令牌
- `model_preview_panel.py`：`_lan_auth_enabled()` / `_lan_auth_cookie()` / `_load_with_lan_auth()`
- 鉴权 cookie 使用独立 `QWebEngineProfile`（避免污染共享 cookie jar）

### 2.3 P1：插件权限按 plugin_id 隔离 + services() 白名单

**执行者**：DeepSeek-V4-Pro  
**验证**：83 passed, pyright 0/0

**变更**：
- `host_context.py`：`_PluginServicesView` 白名单仅 `metadata_service` / `tag_service` / `thumbnail_service`，拒绝 `sharing_services` / `plugin_service` / `session` / `file_operation_service`（`AttributeError` 让 `hasattr()` 也返回 False）
- 每 `plugin_id` 独立权限计数
- `contextvars.ContextVar[str | None]` 存储执行期 plugin_id，避免多线程钩子回调串话
- **legacy handler arity fix**：`inspect.signature` 在调用前决定形式（context-menu 传路径 vs menu/toolbar 无参），TypeError 不再误判为 arity 不匹配而双重执行

### 2.4 P1：current_session() / current_window() 绕过白名单

**执行者**：DeepSeek-V4-Pro  
**验证**：85 passed, pyright 0/0

**变更**：
- `current_session()` / `current_window()` / `current_services()` 全部门禁 `PERMISSION_HOST_SERVICES`
- **发现更大漏洞**：`ctx.window` → `window._bootstrap`（`PluginService` 特权升级）+ `window._scoped_services_for_session`（`token_secret` 泄露）
- `window._bootstrap` / `window._scoped_services_for_session` 均改为 `@require_permission(PERMISSION_HOST_SERVICES)`
- 零已发布插件使用 `ctx.window` / `ctx.session`，门禁未破坏现有功能

### 2.5 P1：PBKDF2 测试降档（60 万迭代 → 快速模式）

**执行者**：DeepSeek-v4-flash  
**验证**：134 passed subset, 全量 120.26s (AM_REAL_PBKDF2=1) vs 估算套件节省 ~70s

**变更**：
- `domain/auth.py`：提取 `KEY_ITERATIONS = 50_000`，生产默认 600k/100k/50k 不变
- `tests/conftest.py`：function-level autouse `_fast_pbkdf2` 覆盖三常量为 LEGACY=600 / PASSWORD=1000 / KEY=500
- `tests/unit/test_domain_auth.py`：新增 `TestProductionCosts`（4 tests，`@pytest.mark.real_pbkdf2_cost`）
- `TestCrossCostVerification.test_production_cost_hash_verifies_under_test_cost` 验证版本化哈希内嵌迭代数的核心场景

---

## 3. 手动修复（5 项）

### 3.1 .gitignore 通用模式 + previewer-dist 决策

**变更**：
- 通用模式替代逐个探针文件名：`/.pytest-*/` / `/.bt-*/` / `/*_files.txt` / `/_*`
- `/_*` 根锚定，65 个合法下划线前缀模块文件在子目录中仍被追踪
- **previewer-dist 决策**：入版本控制（无构建脚本，fresh clone 否则死链），但排除 `**/*.map` 和 `samples/`（13 MB → 3.19 MB）

**验证**：
- 0 个已追踪文件被新规则忽略
- previewer-dist: 43 files/12.95 MB → 25 files/3.19 MB

### 3.2 panels/file_list/_actions.py 双重提示 bug

**变更**：
```python
execute = getattr(svc, "execute_command", None)
if callable(execute):
    # v2 operator 同时注册在 _v2_commands 和 _commands（legacy 兼容）
    # 必须无条件 return，否则 fallthrough 到 get_commands 会通过
    # _operator_handler 闭包再次调用，触发两次参数对话框
    execute(command_id, extra_paths=[file_path])
    return
```

**根因**：`_register_operator_class` 在 L415 将 `_operator_handler` 作为 legacy handler 注册到 `_commands`，`window.py:1088-1108` 已有正确形式（无条件 return）

### 3.3 previewer_static.py 文档修正

**变更**：
- docstring 和 503 消息中的不存在脚本 `scripts/build-previewer.ps1` → "外部工作区产物，缺失表示检出不完整而非未构建"

### 3.4 plugin-api-v2-handover.md 更新

**变更**：
- ✅ 77 项 → ✅ 83 项插件相关测试（权限隔离一轮后 +6）
- "待后续工作（可选）" → "已在后续轮次补齐" 记录四项完成
- 新增 "## 4. 仍未完成"：
  - undo stack 仅覆盖 v2 operators，`undo_last_command()` 无 UI 入口点
  - `database.*` / `network.request` / `clipboard.*` / `filesystem.write` / `settings.read` 定义未强制
  - `register_*` 归属记录不匹配

### 3.5 README.md 统计更新

**变更**：
- L8：WebUI **106 文件 / 705 passed** 实测（原 683 passed 过时）
- L366：同步更新，修正"未复跑"说明

**验证**：`check_doc_stats.py` → "README stats are current"

---

## 4. 已知未修复（6 项）

### 4.1 刻意接受（2 项）

| 项目 | 理由 |
|------|------|
| /api/model 位图侧车无 Pillow 内容校验 | Content-Type 白名单 + `nosniff` 已阻止 active content；添加校验可能拒绝合法 16-bit PNG / TGA 变体纹理 |
| `undo_last_command()` 无 UI 入口点 | 插件默认禁用，零已发布插件声明 undoable operator；提前连线属于推测性工作；gap 已记录在交接文档 |

### 4.2 子智能体标记但未修复（3 项）

| 项目 | 标记者 | 原因 |
|------|--------|------|
| `preferences(plugin_id)` 跨插件访问 | plugin permission agent | 插件 A 可读写插件 B 的偏好包；需架构决策（隔离 vs 共享场景） |
| `register(host)` 暴露 `unregister_plugin()` | plugin permission agent | 原始 `PluginHostContext` 传给 `register()`，插件可注销其他插件 |
| `types.py` `_runtime_session` duck-typing fallback | plugin permission agent | 死代码，保留以兼容公开 API |

### 4.3 新发现未派遣（1 项）

**test_gallery_incremental.py `-n auto` 非确定性失败**

**表现**：
- 3/4 PBKDF2 agent runs 出现，0/1 final run 出现
- 签名：incremental vs oracle snapshot 不匹配 + `UnicodeDecodeError: invalid start byte 0xb4`
- 每次失败的测试名不同，`PytestUnhandledThreadExceptionWarning` 证明后台线程
- 单进程 `-n 0` 运行 14/14 通过

**根因假设**：
1. `_image(path)` 调用 `PIL.Image.save(path)` 写入 PNG，无 `fsync`
2. `GalleryService` 后台线程响应 `FileSystemChanged` 事件扫描目录
3. `_describe_image()` → `Image.open(path)` 读到部分写入的文件
4. `0xb4` (180) = 默认 RGB 颜色 `(20, 80, 180)` 第三分量，PIL 期望 PNG 头 `89 50 4E 47`

**修复方向**（按优先级）：
- P0：`_image()` 添加 `fsync` + `os.sync()`
- P1：`_describe_image()` 添加 PNG 头校验，遇格式错误返回 `None`
- P2：`_settle()` 首次轮询前 0.1s 延迟（给写入完成时间）
- P3：`@pytest.mark.no_xdist` 禁用这 14 个测试的并发

**接受理由（如选择不修复）**：
- 生产代码已容错：`_image_dimensions()` 捕获所有异常返回 `None`
- 测试最终通过：重试或单进程运行均绿
- 真实场景罕见：用户不会在文件写入未完成时立即触发扫描
- CI 可单独跑：`pytest tests/integration/test_gallery_incremental.py`

---

## 5. 架构观察

### 5.1 数据访问模式

| 指标 | 值 | 备注 |
|------|---|------|
| `application/` 层原始 SQL 调用 | 92 | reconciliation_queue_store.py (46), database_integrity_service.py (11), file_operation_service.py (10), undo_service.py (8) |
| `application/` 导入 repositories | 20 | asset_index, auth, favorite, metadata, order, project, quota, search, seller_profile, share, shop_buyer, shop, storefront_analytics, tag, thumbnail 等 |

**评价**：
- `reconciliation_queue` 作为事务编排器，raw SQL 合理
- `undo_service` 快照三表（file_tags / file_meta / library_favorites），raw SQL 避免 repository 抽象税
- `file_operation_service` 使用 `SAVEPOINT` 事务边界，raw SQL 控制保存点生命周期

### 5.2 技术债务

| 项目 | 状态 |
|------|------|
| 大型模块 | `window.py` 1151 行，`file_operation_service.py` 1000+ 行，`info.py` 大型 widget |
| mixin 复杂度 | `file_list/` 跨多个 mixin |
| 测试性能 | `shutdown_stress` 52.46s 占全量运行一半时长 |

### 5.3 性能基础设施（已有）

- `directory_cache` 表（v5 迁移），schema v29
- `PerformanceRecorder` 可选遥测
- `asset_service` / `gallery_service` 已接入
- Cython `color_utils.c` 存在

---

## 6. 下一步建议

### 6.1 立即行动（建议）

1. **决策 `test_gallery_incremental.py` flake**：修复（P0/P1）或接受（单进程 CI）
2. **决策 `preferences(plugin_id)` 跨插件访问**：隔离（修改 API）或文档化（允许共享）
3. **决策 `DeepSeek Docs/` 目录名**：保持现状或规范化（已有先例：`.Cython&Noikta/` → `.cython-nuitka/` staged）

### 6.2 中期优化（可选）

1. **性能**：
   - 调查 `shutdown_stress` 52.46s，考虑拆分或超时优化
   - 扩展 `PerformanceRecorder` 覆盖更多服务
   
2. **债务**：
   - 拆分 `window.py`（UI 层 vs 业务逻辑）
   - 重构 `file_list/` mixin 为组合优先

3. **插件系统**：
   - 强制权限声明（`database.*` / `network.request` / `clipboard.*` / `filesystem.write` / `settings.read`）
   - 连线 `undo_last_command()` UI（如有插件需求）

---

## 附录 A：验证命令

```bash
# 全量 Python 套件
python -m pytest -p no:randomly -n auto --dist worksteal --basetemp=.pytest-final -q

# 静态门禁
python -m ruff check .
python scripts/check_layers.py
python scripts/check_doc_stats.py
python scripts/check_boundaries.py
python scripts/check_style_sources.py
npx pyright --outputjson

# gallery incremental 单独跑（避免 -n auto flake）
python -m pytest tests/integration/test_gallery_incremental.py -v
```

---

**审查完成时间**：2026-08-17  
**最终状态**：✅ 3722 passed, 7 skipped, 0 failed + 所有静态门禁通过
