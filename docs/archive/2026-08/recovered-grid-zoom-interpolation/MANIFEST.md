# 抢救自孤儿 worktree：fix/grid-zoom-interpolation

- 抢救时间：2026-08-31
- 来源：`.worktrees/grid-zoom-interpolation-fix/`（8/13 的工作树快照，未注册到 git）
- 分支：`fix/grid-zoom-interpolation`，HEAD = `0885d77c74baa6caa94f0a6e98b155a5f3fef399`
- 判定：逐字节比对确认这 24 个文件**既不在主仓库、也不在 `mirror/AssetsManager-2026-08-13.bundle` 分支内容中**，属于该工作树的独有未提交工作。
- 处置：先复制到此处留存，随后回收整个 `.worktrees/` 目录（约 346 MB，其中 340 MB 是可再生的 RuntimeData）。

## 文件清单

| 文件 | 大小 | SHA256 前 12 位 |
|---|---|---|
| `AssetsManager/lan/server.py` | 18.0 KB | `21e2a810b4bc` |
| `docs/compose/plans/2026-07-24-cookie-only-spa-auth.md` | 6.1 KB | `0010ec9abd11` |
| `docs/compose/reports/2026-07-22-grid-zoom-investigation.md` | 4.6 KB | `09a1572f8b36` |
| `docs/compose/reports/2026-07-23-python-session-desktop-closure.md` | 12.6 KB | `a51d6b38023d` |
| `docs/compose/reports/2026-07-24-cookie-only-spa-auth-remediation.md` | 3.0 KB | `e02d255d4182` |
| `docs/compose/reports/2026-07-24-webui-lan-contract-closure.md` | 12.3 KB | `12edf148f065` |
| `docs/compose/reports/2026-07-26-real-lan-acceptance.md` | 11.5 KB | `2771743ddcf7` |
| `docs/compose/reports/2026-07-27-weekly-stability-closeout.md` | 10.0 KB | `b0610b60fa12` |
| `docs/compose/reports/2026-07-28-real-lan-acceptance-day5.md` | 7.5 KB | `00258b628427` |
| `docs/compose/reports/2026-07-28-real-lan-acceptance-day6.md` | 3.5 KB | `1cdb63823d19` |
| `docs/compose/specs/2026-07-24-cookie-only-spa-auth-design.md` | 3.2 KB | `18fba3cc7def` |
| `tests/desktop/test_plugin_manager_dialog.py` | 3.7 KB | `29f9440e995b` |
| `tests/desktop/test_settings_dialog.py` | 2.2 KB | `67af54ee9335` |
| `tests/desktop/test_tag_editor_dialog.py` | 3.5 KB | `97d3c2710c5c` |
| `tests/integration/test_scoped_projection_ordering.py` | 3.7 KB | `5f41b4c806ee` |
| `tests/lan/test_lan_api.py` | 134.1 KB | `6eb94fe4e492` |
| `webui/package.json` | 0.8 KB | `e3312af2a916` |
| `webui/src/App.tsx` | 1.1 KB | `58d8491473c3` |
| `webui/src/components/layout/Sidebar.test.tsx` | 1.8 KB | `0b6d5274719d` |
| `webui/src/pages/BrowsePage.test.tsx` | 11.0 KB | `87fb4e284d24` |
| `webui/src/pages/LoginPage.test.tsx` | 1.0 KB | `fce61425cdd5` |
| `webui/src/pages/LoginPage.tsx` | 18.4 KB | `e77ebf00133b` |
| `webui/src/stores/AuthContext.test.tsx` | 2.6 KB | `e212d9769c76` |
| `webui/src/stores/AuthContext.tsx` | 3.9 KB | `7a8a8c598538` |

## 内容审查结论(2026-08-31)

逐一比对抢救版与主仓库当前 HEAD(2026-08-31)后的判定:

### A. 已被主仓库超越(13 个,无需恢复)

| 文件 | 主仓库现状 | 判定依据 |
|---|---|---|
| `AssetsManager/lan/server.py` | 54.6 KB(8/28 `6323156` 重写) | 抢救版 18 KB 为旧单体结构(`_LanServerImpl` 类),8/28 已拆生命周期+鉴权链统一 |
| `tests/lan/test_lan_api.py` | 225.5 KB / 210 用例(8/28 `c31f874`) | 抢救版 134 KB / 144 用例,旧版本 |
| `tests/desktop/test_plugin_manager_dialog.py` | 3.9 KB(8/28 `b8fb299`) | 主仓库新版更全 |
| `tests/desktop/test_settings_dialog.py` | 5.3 KB(8/28 `b8fb299`) | 同上 |
| `tests/desktop/test_tag_editor_dialog.py` | 3.5 KB(8/28 `b8fb299`) | 同上 |
| `webui/src/App.tsx` | 6.8 KB | 主仓库独有行 131 vs 抢救版 16 |
| `webui/src/pages/LoginPage.tsx` | 20.4 KB | 主仓库独有行 86 vs 抢救版 62 |
| `webui/src/stores/AuthContext.tsx` | 11.8 KB | 主仓库独有行 243 vs 抢救版 77(8/27 `edd2bf2` 后持续演进) |
| `webui/src/components/layout/Sidebar.test.tsx` | 16.8 KB | 同上 |
| `webui/src/pages/BrowsePage.test.tsx` | 49.8 KB | 同上 |
| `webui/src/pages/LoginPage.test.tsx` | 3.5 KB | 同上 |
| `webui/src/stores/AuthContext.test.tsx` | 16.1 KB | 同上 |
| `webui/package.json` | 1.1 KB | 依赖已演进 |

### B. 仍有效,已恢复(1 个)

- `tests/integration/test_scoped_projection_ordering.py`(3.7 KB)——主仓库无此路径,且与 `test_url_projection_contract.py` 非替代关系(前者测 domain 层 `FileSystemChanged` 投影-消费顺序不变量,后者测 LAN URL 契约)。
- 引用的 API 全部存活:`ApplicationBootstrap`(bootstrap.py:296)、`library_service.open_session`(library_service.py:1186)、`file_operation_service.copy_to_directory`(file_operation_service.py:813)、`asset_index_service`(bootstrap.py:245)、`EventBus._instance`(domain/event_bus.py:26)。
- **已于 2026-08-31 复制回 `tests/integration/`**。待有 pytest 环境(含 PySide6)时运行验证;本项目 .venv 为 WSL 专用,Windows 侧暂缺依赖。

### C. 历史审计文档(10 个,保持留档)

7/22–7/28 的 LAN 验收/稳定性报告(Day2–Day7 real LAN acceptance、cookie-only SPA auth 方案/修复/设计)。结论已被 8/28 蒸馏(68 批审计→单页总结)覆盖;主仓库 `docs/compose/` 与 `docs/archive/2026-08/compose-raw/` 均无同名副本,本目录即为归档位。无需移动。
