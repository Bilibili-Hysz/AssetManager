# 交接提示词（重启会话后粘贴使用）

继续维护 AssetsManager（PySide6 桌面资产管理器 + aiohttp LAN 服务器 + React SPA）。

工作目录：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak`。本地 git master，**无远程**；每次提交后执行 `git bundle create mirror/AssetsManager-2026-08-15.bundle --all` + `git bundle verify` 刷新备份。

先读 `docs/HANDOVER-2026-08-15.md`，里面记录了完整架构承重墙（五层 DI、五条边界规则、DB 迁移 frozen v29）、门禁命令、主题/视觉体系、本会话已完成的所有工作（§4，**不要重做**）和待办（§5）。

当前 HEAD：`096c57b`，工作树干净。`.mimocode/plans/1784045171846-playful-orchid.md` 在 status 中显示为 `D`，是外部工具工件，**不要 touch/commit/恢复**。

门禁（提交前必跑）：
- `python -m ruff check AssetsManager tests scripts run.py`
- `python -m pyright`（0e0w；新增模块要加进 `pyrightconfig.json` 白名单）
- `python scripts/check_boundaries.py`
- `python -m pytest tests -n 0 -q`（不传 --basetemp；4 个 multiprocessing named-pipe EPERM 失败、watcher dot 与 share_download 偶发，均不算回归）

从待办继续即可，优先方向：
1. 视觉「拓展主题」阶段（三阶段顺序的最后一段，尚未开始）；
2. 或用户新指定的方向。

如需委派子代理：用 `workflow` 脚本内 `agent(prompt, {provider:"opencode-go", model:"deepseek-v4-pro"})`（复杂任务）/`deepseek-v4-flash`（轻量）；子代理禁止 git commit，成果由主智能体亲自复核再提交。细节见 skill `custom-subagents`。
