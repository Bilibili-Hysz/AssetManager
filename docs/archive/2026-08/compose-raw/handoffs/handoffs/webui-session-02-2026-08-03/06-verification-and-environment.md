# 06 — 验证命令与环境说明

## 1. WebUI 基线命令

从仓库根目录执行：

```powershell
npm --prefix webui test -- --run
npm --prefix webui run typecheck
npm --prefix webui run build
```

或进入 `webui` 后执行：

```powershell
Set-Location "D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui"
npm test -- --run
npm run typecheck
npm run build
```

2026-08-03 基线结果：

| 命令 | 结果 |
|---|---|
| `npm --prefix webui test -- --run` | 37 files / 292 tests passed |
| `npm --prefix webui run typecheck` | passed |
| `npm --prefix webui run build` | passed，1632 modules transformed |

`webui/dist` 是 LAN 生产 SPA 的构建输出；真实 Chromium acceptance 要先确保它是当前源码构建的产物。

## 2. Python/LAN/Chromium

从仓库根目录执行：

```powershell
python -m pytest -q tests/e2e/test_webui_realtime_acceptance.py
python -m pytest -q tests/lan/test_runtime_realtime.py
python -m pytest tests/lan/test_runtime_realtime.py tests/e2e/test_webui_realtime_acceptance.py -q
```

实时数据流 hardening 报告还列出：

```powershell
python -m pytest tests/lan/test_public_contracts.py tests/lan/test_t2_t4_contracts.py tests/lan/test_role_permissions.py tests/unit/test_architecture_boundaries.py -q
python -m pytest tests/lan -q
```

如果需要从受限 Windows 环境运行 Python 测试，优先把 pytest 临时目录指向仓库外且明确可写的目录；不要把环境 ACL 失败误判成产品测试失败。测试前确认 Playwright/Chromium 已安装。

## 3. 外置 Git 环境

当前会话的 Git 元数据目录：

```text
C:\Users\86177\.codex\visualizations\2026\07\31\019fb82d-6e7b-7731-9239-2a0d66ff4c54\assetsmanager-git-metadata-99e3971
```

常用操作：

```powershell
$repo = "D:\~Vibe-Coding\Projects\AssetsManager_old-bak"
$gitDir = "C:\Users\86177\.codex\visualizations\2026\07\31\019fb82d-6e7b-7731-9239-2a0d66ff4c54\assetsmanager-git-metadata-99e3971"

git --git-dir=$gitDir --work-tree=$repo status --short
git --git-dir=$gitDir --work-tree=$repo diff --check
git --git-dir=$gitDir --work-tree=$repo log -5 --oneline
```

只检查交接包：

```powershell
git --git-dir=$gitDir --work-tree=$repo diff -- docs/compose/handoffs/webui-session-02-2026-08-03
git --git-dir=$gitDir --work-tree=$repo add -- docs/compose/handoffs/webui-session-02-2026-08-03
git --git-dir=$gitDir --work-tree=$repo diff --cached --check
```

不要用普通 `git status` 作为当前状态真相；它会读取原 `.git`，而原 `.git` 仍可能显示旧的未提交文档。

## 4. 证据记录要求

每个任务结束时记录：

- 精确日期；
- 命令和工作目录；
- 通过数量、构建模块数或失败摘要；
- 是否使用临时库、真实库、headless Chromium、移动 viewport；
- 是否存在环境阻塞；
- 代码与文档是否已经提交；
- 外置 Git HEAD 和工作树状态。

历史报告中的测试数字必须注明 `historical snapshot`。尤其不要把 `task-14-browser-realtime-acceptance.md` 里旧的 251、`realtime-dataflow-hardening.md` 里旧的 256 或其他旧总数作为当前门禁。

## 5. 当前已知环境限制

- Chromium Playwright 曾出现 Windows `spawn EPERM`；若复现，先记录环境阻塞，不要修改产品代码绕过。
- Windows 默认 pytest temp 目录 ACL 曾导致误报；改用明确可写的 basetemp 后再判断。
- 原 `.git` 对当前 Codex 沙箱仍不适合作为可写元数据，继续使用外置 Git。
- Pyright 独立审查发现过 78 条诊断；旧文档中的 41 条已过时，不能混用。
- WebUI 通过 jsdom/Vitest 不代表真实浏览器布局、文件下载、WebSocket、触控或图片解码已经通过。

## 6. 视觉与浏览器验收

DeepSeek 规划中的截图遍历、主题对比度、动效降级和真实窗口矩阵，迁移到 WebUI 后至少覆盖：

- viewport：375px、768px、1024px、1440px；
- theme：dark、light、系统偏好；
- state：loading、empty、error、unauthorized、retry、broken thumbnail、selected、focus-visible；
- motion：默认 hover/zoom 与 `prefers-reduced-motion: reduce`；
- surface：Landing、Browse Grid/List、Detail、ShareReceive、ShareDialog、Admin；
- 证据：真实 Chromium 截图或明确记录 Playwright/环境阻塞，不能用 jsdom snapshot 代替布局验收。
