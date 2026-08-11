# G8 P2 repository error contract

日期：2026-08-06  
范围：AuthRepository、TagRepository、ShareRepository 的基础设施错误与真实业务失败分类。

## 1. Auth

AuthRepository 现在区分：

- 真实无用户/无邀请码 → 保持 `False`/空结果；
- 重复用户名、重复邀请码、无效/已消费邀请码 → 保持既有业务失败返回；
- closed connection、schema `OperationalError`、`ProgrammingError`、生命周期/ownership 错误 → 传播或包装为可识别基础设施异常。

`AuthService.register_user()` 继续使用严格邀请码检查，数据库故障不会被当作无需邀请码。

## 2. Tag

TagRepository 的 `add_tag()`/`remove_tag()` 删除宽泛 `except Exception -> False`：

- 重复添加与删除不存在 tag 仍保持幂等业务语义；
- closed connection、schema、ownership、lifecycle 错误直接传播。

## 3. Share

ShareRepository.insert() 仅对明确的 `IntegrityError` 返回 `False`：

- 约束冲突仍是业务/持久化失败；
- closed connection、schema、ownership、lifecycle 错误不再伪装成创建失败。

## 4. 验证

```text
P2 repository 专项：132 passed

python -m pytest -q --tb=short tests/core tests/unit tests/integration tests/desktop tests/lan
2275 passed, 4 skipped, 1 warning

ruff check AssetsManager tests
All checks passed

pyright
0 errors, 0 warnings, 0 informations

git diff --check
通过；仅有工作树既有 LF/CRLF 转换提示
```

4 条 skip 为当前 Windows 缺少 symlink/directory-symlink 权限；1 条 warning 为既有 zipfile duplicate-name 测试警告。

## 5. 下一阶段设计任务

- SearchService partial/degraded result contract：区分真实空结果、单 tag 失败、provider unavailable、index schema failure，并兼容当前 LAN/desktop transport。
- 继续清理剩余 Auth/Tag/Share/Metadata broad catches，但每次只收口可证明的基础设施异常。
- `allow_unmanaged=True`：建立插件与历史 fixture 迁移矩阵后，再评估拒绝默认或 capability token。
- WebUI/E2E 仍未纳入主线验收。

## 6. 工作区事实

- 分支：`master`。
- HEAD：`fbf3403`；该提交由并行代理创建，主会话未执行 staging/commit/reset/checkout/clean。
- 暂存区为空；工作区仍为多会话混合 dirty 状态。
