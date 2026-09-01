# G12：AuthService / ShareService canonical session contract

> 日期：2026-08-06
> 工作区：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak`
> 分支：`master`
> 本报告是主线继续开发记录，不是发布完成声明。

## 1. 阶段目标

承接 G11 的 core store session binding，处理 canonical runtime 中 AuthService / ShareService 虽然已经接收 `session`，但构造时仍未验证 connection ownership 的缺口。

本阶段目标：

- canonical session 构造时验证 connection 属于当前 session；
- session 关闭后继续由 `session_operation` 拒绝数据库操作；
- 保留 `session=None` 与历史 fake session/raw connection 兼容；
- 不改变 token、密码、share path 和 repository 业务语义。

## 2. 实现内容

修改：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\auth_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\share_service.py
```

### 2.1 统一 `_bind_session()` 合同

两个 service 均新增内部绑定流程：

```python
_bind_session(session)
```

行为：

1. 禁止同一 service 重新绑定到另一个 session；
2. 如果 session 暴露 `connection_for()`，校验返回的连接对象必须与 service 当前 `_conn` 完全一致；
3. 保存 session、library root、session token；
4. 构造函数传入 session 时立即执行 binding。

canonical `LibrarySession` 连接不一致时，构造直接失败：

```text
ValueError: AuthService connection does not belong to the LibrarySession
ValueError: ShareService connection does not belong to the LibrarySession
```

### 2.2 Fake/legacy session 兼容

历史测试 fixture 中部分 fake session 只提供：

```text
root_str
operation
event_token
```

不提供 `connection_for()`。这类 session 仍然允许用于 legacy compatibility 测试；只有具备 canonical `connection_for()` 的 session 才执行严格 connection ownership 校验。

`session=None` raw service 构造保持不变。

## 3. Bootstrap 影响

`ApplicationBootstrap` 原有 canonical 组装已经传入：

```python
AuthService(connection, token_secret, session=session)
ShareService(connection, token_secret, session=session)
```

本阶段没有改变 bootstrap 资源图，只让这两个构造现在真正验证 connection/session 一致性。

## 4. 新增回归

新增：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_auth_share_session_binding.py
```

覆盖：

1. bootstrap 构造的 AuthService / ShareService 绑定当前 session；
2. service connection 与 session connection 是同一对象；
3. session 关闭后 auth/share 数据库操作均拒绝；
4. canonical-like session + foreign connection 构造失败；
5. 无 `connection_for()` 的 legacy fake session 仍兼容。

## 5. 定向验证

```text
python -m pytest -q --tb=short tests/integration/test_auth_share_session_binding.py tests/integration/test_auth_service.py tests/integration/test_share_service.py tests/integration/test_task_c_producers.py
```

结果：

```text
75 passed
```

静态门禁：

```text
ruff check 相关文件 -> All checks passed
pyright 相关文件 -> 0 errors, 0 warnings, 0 informations
git diff --check -> 退出码 0
```

## 6. 全量非 E2E 门禁

```text
python -m pytest -q --tb=short tests/core tests/unit tests/integration tests/desktop tests/lan
```

结果：

```text
2300 passed, 4 skipped, 1 warning
```

全量静态门禁：

```text
ruff check AssetsManager tests -> All checks passed
pyright -> 0 errors, 0 warnings, 0 informations
git diff --check -> 退出码 0
```

4 条 skip 仍为 Windows 当前进程缺少 symlink/directory-symlink 权限；1 条 warning 仍为既有 zipfile duplicate-name warning。

## 7. 尚未完成

G12 只收口了 Auth/Share application service 的 canonical connection/session contract，不代表 repositories 已完全 session-bound。仍有：

- AuthRepository / ShareRepository raw constructor；
- TagRepository / MetadataRepository / AssetIndexRepository raw constructor；
- PluginMetadataRepository 的 raw compatibility；
- benchmark、历史 fixture、第三方/历史插件矩阵；
- raw adapter 可观测、静态禁止新增；
- 最后切换 `allow_unmanaged` 默认值。

当前仍不可直接执行：

```python
allow_unmanaged: bool = False
```

## 8. 下一阶段建议

按风险从低到高继续：

```text
AuthRepository / ShareRepository session/root-bound adapter
→ MetadataRepository / TagRepository / AssetIndexRepository contract
→ PluginMetadataRepository raw adapter
→ benchmark/history fixture 迁移
→ plugin compatibility matrix
→ 最后切换 allow_unmanaged 默认值
```

Repository 迁移必须保留低层 raw repository 测试，同时为 canonical 路径新增：

- same-root managed connection；
- managed foreign-root；
- unmanaged raw；
- closed connection；
- session closing/closed；
- old repository retained after session reopen。

## 9. 当前质量判断

> G12 已完成 AuthService / ShareService canonical session contract，并通过 2300 条非 E2E 回归和静态门禁。AssetsManager 整体仍未完成，下一阶段进入 repository session/root-bound contract 迁移。
