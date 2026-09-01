# 完整盘点与多专家交叉验证报告(2026-09-02)

> 状态:**LIVING(审计盘点)** · 方法:主代理采集地面真相基线 + 并行派出 4 个专家子代理(文档架构 / 代码工程 / Git安全配置 / 交付依赖构建)各自独立盘点并回答同一组共享验证题,结果交叉比对。所有盘点均为**只读**,未修改被审系统。
> **整改追踪(2026-09-02 更新)**:P0 断链已修(compose/README:47、migrations.md:201、adr 计数,commit affb8f6)+ 迁移遗留断链 28 处已修(deepseek-archive 21 处→baseline、compose migration 7 处→compose-raw 归档);P1-A 已执行(build.py 接入 webui 自动构建,commit ff1e0de);P1-B 已于收尾执行(setup_cython.py 删除 + ruff.toml/clean_runtime.py/README 三处宣传清理);outputs/ 去重已执行(11 文件移除:9 份 md 确认与 docs 等价、2 图标迁移至 assets/icons 并入库,outputs/ 加入 .gitignore);**P2 经复核为已消化**——requirements-ci.txt 精确 overlay + requirements.txt 语义化上界系既定策略(见其文件头注释),overlay 钉版均落在基础区间内,无需改动。

## 一、结论速览

| 维度 | 结论 | 置信度 |
|---|---|---|
| Git 仓库健康 | `fsck` broken=0 / missing=0;42 个 dangling 对象(恢复遗留,无害) | 高 |
| 敏感信息 | 4 个专家独立扫描均 0 真实密钥/Token 泄露 | 高 |
| 误提交垃圾 | 被跟踪文件中 0 个 `.pyc/__pycache__/*.log/*.exit/*.tmp/node_modules/dist/build/*.db/*.lock` | 高 |
| 跟踪文件总数 | 1522(4 专家实测完全一致) | 高 |
| 文档分类 | `docs/README.md` 8 类框架成立,仅 adr 计数轻微漂移 | 高 |
| 文档链接 | compose/、deep-weakness-audit/、migrations.md 等处存在 9+ 处真实失效链接 | 高 |
| 构建闭环 | `webui/dist` 未被 `build.py` 产出、Cython 脚本孤立 → 闭环缺口 | 中-高 |
| `outputs/` | 11 文件入库且未 gitignore(2 图标 + 9 份与 `docs/` 重复的报告快照) | 中 |

## 二、跨专家验证矩阵(共享验证题实测)

| 验证项 | 文档专家 | 代码专家 | Git安全 | 交付专家 | 地面真相 | 一致性 |
|---|---|---|---|---|---|---|
| S1 跟踪文件数 | 1522 | 1522 | 1522 | 1522 | 1522 | ✅ 完全一致 |
| S2 broken/missing | — | — | 0 | — | 0 | ✅ |
| S2 dangling | — | — | 42 | — | 42 | ✅ |
| S2 `.py`/`.pyc`/`.js,.ts` | — | 648 / 0 / 84 | — | — | 一致 | ✅ |
| S3 误提交垃圾计数 | 0(孤儿待定) | 0 | 0 | 0(+outputs) | 0(仅 outputs 未忽略) | ✅(除 outputs) |
| S4 密钥/Token 泄露 | 0(docs 域) | 0 | 0(两遍扫描) | 0(27 误报) | 0 | ✅ 完全一致 |

> 4 个专家在 S1/S4 上**零分歧**,S2/S3 仅存在计数口径差异(reports 顶层 39 vs 含子目录 47;outputs 是否算"应忽略")与范围覆盖差异,无事实冲突。

## 三、分域发现

### A. 文档与知识架构(专家①)
- **分类框架有效**:`docs/README.md` 8 类(① LIVING 事实 ② 08-01 基线 ③ 审计评审 ④ plans ⑤ compose 证据 ⑥ reports ⑦ diagrams ⑧ archive)均指向真实目录,无悬空类。
- **状态头覆盖不全**:`docs/plans/` 14 份中仅 6 份有文首显式状态头(architecture-reliability-roadmap、bg-gpu-shader、documentation-maintenance-plan、p0-security、task-package-2026-09-01、workspace-cleanup-plan);其余 8 份仅靠 `docs/README.md` 散文描述,其中 `task-package-2026-08-30.md` 已被标"已被取代"但自身无头。
- **真实失效链接(建议下轮修复)**:
  - `docs/compose/README.md:47` → `../../archive/INDEX.md`(应为 `../archive/INDEX.md`,已实测确认失效)
  - `docs/archive/2026-09/compose-reports/desktop-lan-webui-architecture-migration.md:43,44,47,48,121,123,200` → 7 处 `../plans|specs/2026-07-21-*.md`(实际在 `archive/compose-raw`)
  - `docs/deep-weakness-audit-2026-08-22/10-full-review-reconciliation.md:22–26` → 5 处 `../full-review/*.md` 证据文件不存在
  - `docs/migrations.md:201` → `full-review/c6-c10-convergence-2026-08-21.md` 不存在
  - (`deepseek-archive-2026-08-25/`、`archive/2026-08/compose-raw/` 内大量失效链接属"选择性迁移/历史原件"设计性残留,非缺陷)
- **FROZEN 纪律合规**:`git diff HEAD` 对 `baseline-2026-08-01/`、`deep-weakness-audit-2026-08-22/` 均为空 → 冻结目录未被改写。
- **索引轻微漂移**:`docs/README.md` 称 `adr/` 为 0001~0003,实际含 0001~0005(0004/0005 已被 plans 引用)。

### B. 代码工程与质量(专家②)
- **webui 177M 为误报**:磁盘 177M 实为 `webui/node_modules/`(被 `.gitignore` 忽略,跟踪 0);git 仅跟踪 211 文件 / 1.6M 源码,无 `dist/build` → 无误提交产物。
- **`AssetsManager/` 结构清晰**:16 个子包分层合理;TODO/LEGACY 仅 8 文件 15 处,多为 `_LEGACY_URL_KEYS` 等向后兼容常量,非废弃代码。未做全量 import 图,未发现明显孤儿模块。
- **`Plugins/`(2 插件 + Docs)、`scripts/`(约 17 脚本)健康**,无明显过期重复。
- **测试覆盖充分**:测试 `.py` 326 vs 源码 `.py` 275(约 1.2:1)。`tests/lan/test_lan_api.py` 历史含多个 ~240KB 旧版本(历史膨胀,不影响工作区)。

### C. Git 仓库 / 安全 / 配置(专家③)
- **仓库健康**:broken=0、missing=0;42 dangling(blob+commit)为对象库恢复/重写遗留,无害,不影响 `git gc`。
- **`.gitignore` 覆盖良好**:`RuntimeData/`(465 `.lock` + 2 `.db`)、`mirror/`(5 bundle)、`*.pyc`、`__pycache__`、`*.log`、`*.db`、`*.lock`、`.venv`、`node_modules`、`dist`、`build` 均未被跟踪 → 无误提交。
- **密钥扫描干净**:严格 + 宽松两遍(`password/secret/token/api_key/sk-/AKID/ghp_/private_key/client_secret/Bearer`),排除 `.md/.txt/.iss/test/example` 后命中 0 处真实凭据。
- **历史大对象 Top10**:全部为 `tests/lan/test_lan_api.py`(~239–245KB × 10 历史版本),合法测试文件,非安全风险。

### D. 交付 / 依赖 / 构建(专家④)
- **依赖一致性**:6 个 `requirements-*.txt`(共 59 行、去重 15 包)**无版本冲突、无未钉版本**;但 `requirements.txt` 采用浮动区间(`Pillow>=10,<13`),确定性仅由 `requirements-ci.txt` 提供 —— 非 CI 安装仍不可完全重现(注释自承 "依赖全浮动")。
- **构建闭环缺口**:
  - `build.py:21-26` 仅调用 `PyInstaller AssetManager.spec`,**不产出 `webui/dist`,也不调用 `setup_cython.py`**。
  - `setup_cython.py:5-10` 编译 4 个热点模块为 `.pyd`,但未被 `build.py` 引用、也不在 `AssetManager.spec` 的 `hiddenimports` → Cython "2–5x 加速"**未接入实际构建闭环**(孤立脚本)。
  - `AssetManager.spec:84` 打包 `webui/dist`,但 `build.py` 不构建它 → 若 `dist` 为空,LAN 服务无 SPA。
- **`outputs/` 入库偏差**:11 文件被跟踪且未出现在 `.gitignore`(2 图标 + 9 份报告快照,后者与 `docs/plans`、`docs/reports` 内容重复,如 `desktop-uiux-optimization-plan-2026-08-29.md`、`port-architecture-2026-08-30.md`、`serpent-vs-assetmanager-2026-08-30.md`)→ 应明确 `outputs/` 定位(交付副本 vs 构建产物)并 gitignore 或去重。
- **门禁配置自洽**:`pytest.ini`/`ruff.toml`/`pyrightconfig.json` 与 11 个 `check_*` 自研门禁互补无矛盾。

## 四、建议处理项(供后续"整理"轮执行,本轮仅盘点)

| 优先级 | 项 | 位置 | 说明 |
|---|---|---|---|
| P0 | 修复文档失效链接 | compose/README:47、compose/reports/desktop-lan-webui-architecture-migration.md(7)、deep-weakness-audit/10-full-review-reconciliation.md(5)、migrations.md:201 | 真实断链,影响导航 |
| P0 | 修正 adr 索引计数 | `docs/README.md` | 0001~0003 → 0001~0005 |
| P1 | 补全 plans 状态头 | 8 份缺文件级头 | 提升可维护性 |
| P1 | 修复构建闭环 | `build.py` / `AssetManager.spec` / `setup_cython.py` | 产出 webui/dist、接入 Cython |
| P1 | 处理 `outputs/` 入库 | `outputs/`(11 文件) | gitignore 或去重交付副本 |
| P2 | 收紧依赖确定性 | `requirements.txt` | CI 外安装不可重现 |
| P2 | 可选 `git gc --prune` | 仓库 | 清理 42 dangling(无害) |

## 五、专家分歧点(已记录)
1. **webui 177M 是否算仓库问题** —— 一致结论:纯本地 node_modules,非仓库负担。
2. **`outputs/` 是否应 gitignore** —— 仅交付专家扫描到,建议忽略/去重;其余专家未覆盖该目录。
3. **`webui/dist` 缺失是否缺陷** —— 代码/交付专家一致判为"构建闭环缺口";需主代理确认是否为"需手动 `npm build`"的设计取舍。
4. **dangling 42 对象 / `test_lan_api.py` 大对象** —— 安全专家判无害;可作可选清理。
