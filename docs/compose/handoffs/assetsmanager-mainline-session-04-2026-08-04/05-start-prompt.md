# 新会话启动提示词

```text
你现在接手 AssetsManager 主线开发。请先完整读取：

1. docs/compose/handoffs/assetsmanager-mainline-session-04-2026-08-04/README.md
2. docs/architecture.md
3. docs/architecture-diagram.md
4. docs/adr/0003-library-runtime.md
5. docs/compose/reports/mainline-parallel-batch-2026-08-04.md
6. docs/compose/reports/g6-1-restore-2026-08-04.md
7. docs/compose/reports/g6-1-product-entry-contract-2026-08-04.md
8. docs/compose/reports/g6-5-database-integrity-2026-08-03.md
9. docs/compose/reports/g6-6-security-preflight-implementation-2026-08-04.md
10. docs/compose/handoffs/desktop-ui-session-03-2026-08-04/README.md
11. docs/compose/handoffs/webui-session-02-2026-08-03/README.md
12. DeepSeek Docs/施行路线图.md
13. DeepSeek Docs/未来方向/05-桌面端UI视觉改进规划.md
14. DeepSeek Docs/未来方向/06-现代化界面技术路线评估.md
15. DeepSeek Docs/未来方向/07-桌面端性能优化计划.md

用户当前的明确要求：

- 先由当前主线全面处理和收口 AssetsManager；
- 暂不进行 WebUI 显示优化；
- 只有主线真正完成后，才告知用户可以重新启用第二会话进行前端显示优化。

第一步只做只读基线：

- 确认分支、HEAD、git status 和暂存区；
- 不执行 reset、checkout、全量 clean、覆盖或格式化；
- 把 webui/** 和 webui/test-results/** 当作并行会话保护域，不读取实现细节也不修改；
- 检查当前 Desktop UI 阶段的 84 passed / 完整 tests/desktop 的 482 passed 证据是否仍与工作树一致；
- 对三个 architecture boundary 测试使用仓库外 basetemp（例如 C:\tmp\assetsmanager-boundary-2026-08-04）复跑，避免仓库内临时路径污染诊断字符串。

当前唯一优先级是 R1：修复 G6-1 restore 的 root/session ownership 和 rollback failure 合同。

R1 只允许围绕以下写域工作：

- AssetsManager/application/library_service.py
- AssetsManager/application/library_export_service.py
- AssetsManager/application/bootstrap.py
- tests/unit/test_library_export_service.py
- tests/unit/test_library_service.py（如存在）
- 必要时新增专属 restore coordinator 测试

R1 必须做到：

1. 旧 session 已关闭但同一 root 已被 replacement session 打开时，旧 export service 的 restore 必须 fail-closed；
2. 通过 LibraryService 的 root-aware reservation 串行化 restore 与 open/close；
3. 没有 coordinator 注入时恢复入口 fail-closed；
4. staging、隔离、安装、quick_check、回滚都在 reservation 内执行；
5. 隔离失败、旧目录恢复失败、锁释放失败不能静默吞掉；
6. 增加 replacement-session、reservation race、installed-check failure、quarantine failure、rollback failure 测试；
7. 明确恢复包成员数、展开大小、压缩比和数据库 snapshot 上限。

R1 不得修改 webui、LAN、FileList 热路径、Desktop 视觉文件或为了过测试而放宽断言。

请先用一个高风险审查子代理审查恢复合同，再用互斥写域实现；阶段结束必须运行 targeted tests、相关 application/core/integration 测试、Ruff、git diff --check，并把结果写入新的 compose report。不要在没有证据时宣布 G6 或 AssetsManager 完成。
```
