# G7 P1 raw resource 与安全错误语义

日期：2026-08-06  
范围：Auth invite fail-open、Thumbnail blur fail-open、integrity cleanup 三态、InfoController/PluginMetadataRepository retained raw resource。

## 1. 安全错误语义

### Auth invite

`AuthRepository.has_active_invite_codes()` 现在：

- 真实无 active invite code → `False`；
- closed connection / SQLite 查询错误 → `InviteCodeLookupError`；
- `AuthService.register_user()` 使用严格模式，不会在数据库不可用时放行需要邀请码的注册。

### Thumbnail blur

`ThumbnailService` 的 blur/tag 查询现在区分：

- 无匹配 tag → `False`；
- 无 blur 配置 → 兼容性 `False`；
- provider、ownership、closed connection、schema 查询错误 → 抛出基础设施异常。

这避免数据库故障被解释为“不需要内容模糊”。

### Integrity cleanup

`DatabaseIntegrityService` 新增 `EXISTS/MISSING/UNKNOWN` 三态：

- 只有明确 `MISSING` 才允许删除 metadata/orphan/baked thumbnail；
- OSError、ValueError、TypeError、RuntimeError、symlink escape、foreign-root 和路径解析异常均为 UNKNOWN；
- UNKNOWN 只记录 integrity issue，不触发删除。

## 2. Retained raw resource

`PluginMetadataRepository` 支持：

- 可选 session；
- root/path containment；
- session operation scope；
- legacy raw connection 构造兼容。

`InfoController` canonical 构造注入 session，并把 plugin repository 绑定到 session/root。`InfoPanel.prepare_library_switch()` 会清除旧 controller 和 scoped services，避免切库后保留旧 DB 能力。

为保持 repository layering，session scope 使用 repository 内部的轻量 adapter，不从 repository 导入 `application.context`。

## 3. 验证证据

```text
P1 专项：98 passed

python -m pytest -q --tb=short tests/core tests/unit tests/integration tests/desktop tests/lan
2209 passed, 4 skipped, 1 warning

ruff check AssetsManager tests
All checks passed

pyright
0 errors, 0 warnings, 0 informations

git diff --check
通过；仅有工作树既有 LF/CRLF 转换提示
```

4 条 skip 为 Windows 当前进程缺少 symlink/directory-symlink 权限；1 条 warning 为既有 zipfile duplicate-name 测试警告。

## 4. 后续 P2 长期任务

- Auth/Tag/Share repository broad catches：至少重新抛出 closed connection、schema、ownership/lifecycle 错误；普通业务失败再保留显式 degraded 结果。
- SearchService：设计带 `partial/degraded/errors` 的查询结果契约，区分真实空结果、单 tag 失败、provider unavailable、index schema failure。
- `allow_unmanaged=True`：完成插件/历史 fixture 迁移矩阵后，再评估拒绝默认或 capability token。
- InfoController legacy raw adapter：继续把 legacy raw 构造限制到明确兼容边界。
- WebUI/E2E：仍保持保护域。

## 5. 工作区事实

- 分支：`master`。
- HEAD：`fbf3403`；该提交由并行代理创建，主会话未执行 staging/commit/reset/checkout/clean。
- 暂存区为空；工作区仍为多会话混合 dirty 状态。
