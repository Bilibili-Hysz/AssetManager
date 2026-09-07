# N2 恢复可靠性 — 验收矩阵行 1/行 2 证据摘要（2026-09-08）

## 快照信息

- 快照 HEAD：`82b74846bbd2d4293fe78c4daf93bd016a5446b1`（主工作区 `git rev-parse HEAD`，工作树干净）
- 快照路径：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\.pytest-tmp-lead-snapshots\n2-recovery-ops`（`git archive HEAD | tar -x` 独立快照）
- 新增测试（仅快照内）：`tests/integration/test_recovery_acceptance_matrix.py`
- 生产代码改动：**0**（`AssetsManager/` 下零改动；未 commit/push）
- 运行命令（快照内执行）：
  `QT_QPA_PLATFORM=offscreen python -m pytest -q -o addopts='' -p no:cacheprovider --junitxml=artifacts/n2-matrix.xml tests/integration/test_recovery_acceptance_matrix.py`
- 结果：**2 passed, 0 failed, 0 skipped, 0 errors**（≈2.4s，exit 0）

隔离方式：所有数据位于 pytest `tmp_path`；每个阶段用独立 `AM_RUNTIME_ROOT`（env + `path_resolver.runtime_root` patch 指向 `tmp_path/runtime-<phase>`）。未触碰任何用户真实资产目录；主工作区除本目录三个 `n2-*` 证据文件外无改动（`.pytest-tmp-lead-snapshots` 已被 gitignore，`git status` 为空）。

## 场景清单（工作包验收矩阵前两行）

### 行 1 · 正常完整备份/恢复 — `test_row1_full_backup_restore_round_trip` PASS

种子：三个原始资产 `中文 50%/hero.png`、`普通/scene.txt`、`未评分/unrated.png`（目录名含中文、空格、字面 `%`）；RuntimeData 写入 tags（含中英混合/大小写差异）、notes（含中文）、urls、rating 5（hero）/ 0（scene）/ NULL（unrated，行存在但从未评分）、favorites（owner `tester`，2 条）、普通集合「普通集合」（成员 hero+scene）、smart collection「高分图片」（规则 `{"extensions": [".png"], "rating_min": 4}`）+ assets 索引。

| 断言组 | 状态 |
|---|---|
| ZIP manifest/digest 校验：每个成员 size/sha256 与 manifest 一致；成员集合闭合（namelist == manifest files + manifest.json）；`validate_backup` valid、`errors==()`、quick_check `ok`、file_count 与备份结果一致 | PASS |
| 原始资产不入 ZIP（ZIP 无任何库根资产成员；全部成员在 `data/` 下） | PASS |
| 恢复到新的目的库运行域：源域备份 → 新 `AM_RUNTIME_ROOT` 域 open（空槽）→ close → `restore_backup(overwrite_existing=True)`；`data_dir`/`previous_data_dir` 均在目的运行域内；archive 本身 SHA-256 前后不变 | PASS |
| 原始资产合同：恢复后库根 walk 的相对路径+SHA-256 全集与恢复前一致；三个文件逐字节相同 | PASS |
| DB 投影全量对比（直接 SQL）：`file_tags`、`file_meta`(notes/urls/rating)、`library_favorites`、`asset_collections`(name/kind/query_json)+members 恢复前后完全相等 | PASS |
| rating 三值显式区分：hero==5；scene==0 且 is not None；unrated is None（0 不被吞、NULL 不回退） | PASS |
| favorites 服务层 `list_paths` 恢复前后一致 | PASS |
| 普通集合成员一致；smart query_json 一致且 `evaluate()` 结果一致（且恰为 hero：rating_min 排除 0 与 NULL） | PASS |
| intent marker 成功后消费（不存在） | PASS |

### 行 2 · 元数据 JSON 导出 — `test_row2_metadata_json_export_contract` PASS

同一种子调用 `export_metadata_json`。

| 断言组 | 状态 |
|---|---|
| 顶层键恰为 `{format, schema_version, exported_at, library, entries}`；format `assetsmanager.metadata`；schema_version 1；`path_format=relative-to-library-root` | PASS |
| 每个 entry 键恰为 `{path, path_type, tags, notes, urls}`、`path_type=="relative"` | PASS |
| 稳定排序：entries 按 `(casefold(path), path)`；tags 按 `(casefold(tag), tag)` 且与 SQL 存储去重后一致；notes/urls 与 SQL 行一致 | PASS |
| 中文与字面 `%` 路径不损坏：`中文 50%/hero.png`、中文 notes 以原始 UTF-8 写出（`ensure_ascii=False`，无 `\u` 转义），`50%` 字面保留 | PASS |
| rating/favorite/collection **不在** JSON 合同：entry 键集不含；整个序列化文本中不含 `rating`/`favorite`/`collection` 字样（按实现的合同断言，非臆测扩展） | PASS |
| 目标替换原子：同目标重复导出完整替换（新 notes 生效）、`bytes_written==st_size`、无 `.metadata.json.*.tmp` 残留 | PASS |

## 实现与工作包的差异/观察

1. **无产品缺陷暴露**。两行全部按现实现通过；`build_metadata_export` 的实际字段集与工作包描述一致（仅 relative path/path_type/tags/notes/urls，无 rating/favorites/collections），测试按实现合同断言。
2. **行号漂移**：工作包基线为 `817419a`，快照 HEAD 为 `82b74846`；`build_metadata_export` 实际位于 `library_export_service_export.py:104-155`、`export_metadata_json` :157-193、`create_backup` :211-374、restore 编排 `library_export_service_restore.py:172-384`。语义与工作包描述一致，仅行号需在下次文档刷新时校正。
3. **FavoriteService 未暴露在 `LibraryScopedServices`**（session 运行时服务容器）——它只存在于 LAN 服务容器。测试需直接 `FavoriteService(session=...)` 构造。非缺陷，但若后续行要在服务容器层面统一触达 favorites，需要补一个装配入口。
4. **恢复目标合同的隐含约束（重要）**：`file_meta`/`file_tags`/`library_favorites`/`asset_collection_members` 存的是**库根绝对路径**，restore 无路径重映射。因此「恢复到不同库根路径」会破坏投影（favorites 被 `assert_under_root` 过滤、tags/meta 指向旧路径）。当前受支持的恢复目标是**同库根路径 + 新运行域**（本测试与 W4 演练均采用此方式）。这与工作包「原始资产须仍在同一 library root」一致，但「跨路径迁移恢复」不在当前合同内，应以显式需求另立（含路径重映射或格式升级），不应默认可用。
5. rating 的 `COALESCE` 语义（`database.py:1392` 的 `rating=COALESCE(excluded.rating, file_meta.rating)`）只出现在库内 merge/重映射路径，不在备份/恢复路径；本矩阵证实恢复是整库快照替换，0/NULL 原样保留。
6. 本次运行 ZIP 成员集合为 `data/assetmanager.db`（+manifest）：真实 favorites 存 DB 表 `library_favorites`，单元测试里出现的 `data/favorites.json` 是测试自造文件，并非产品写出的 RuntimeData 文件。

## 建议的后续行（按工作包顺序）

1. **行 3 · 恢复覆盖语义**：archive 含 0/NULL/5，目的库先故意写不同 rating/成员/备注，断言 archive 成为权威、旧 RuntimeData 进隔离区且可由 intent 恢复（本行已搭好的 fixture/投影快照可直接复用）。
2. **行 4 · 中断回滚**：在 quarantine→install 两次 replace 间杀子进程，验证新进程同 runtime root 自动恢复旧 RuntimeData、marker 消费、不产生空 DB（可复用 W4 演练的 barrier 技巧，改成 pytest 子进程）。
3. **行 5 · 损坏归档**：截断 ZIP、改 manifest digest、重复/ canonical-collision 成员 → 恢复在 mutation 前失败、目的态不变、不建立错误 intent/隔离目录。
4. **行 6 · 不可写路径**：staging/隔离区/install 目标用 OSError 注入（Windows 避免 ACL 差异），验证主异常+次级错误保留、fail-closed/ACK 合同。
5. **行 7 · 源资产异常**：恢复后删除/篡改库根原始文件，资产 digest 审计必须显式失败，不得报「完整恢复成功」。
6. 附加建议：将「跨库根路径恢复的绝对路径投影」作为一个明确的场景或产品需求条目（见差异 #4），避免被误当作已支持能力。

## 证据文件

- `docs/reports/week-closeout-2026-09-08-evidence/n2-matrix.xml`（JUnit，2 tests / 0 failures）
- `docs/reports/week-closeout-2026-09-08-evidence/n2-matrix-output.txt`（pytest 输出 + 测试名清单）
- `docs/reports/week-closeout-2026-09-08-evidence/n2-matrix-summary.md`（本文件）
