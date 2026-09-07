# N2 恢复可靠性工作包（2026-09-14 周）

> 状态：待实施。范围限于合成库、临时运行域和可重复的自动化验收；不操作用户真实库。
> 基线：`817419a`。本工作包描述待补合同与最小实施顺序，不把既有单元测试或 W4 演练视为已完成的端到端恢复验收。

## 目标与边界

N2 要证明两类产物各自的合同，并证明恢复失败时旧状态可判定、可保留、可恢复：

| 产物 | 应承诺 | 当前入口 | 不应声称 |
|---|---|---|---|
| 元数据 JSON 导出 | 相对路径、标签、备注、URL 的稳定 UTF-8 JSON；原子发布 | `library_export_service_export.py:104-180` | 原始资产、评分、收藏夹、集合成员已被导出 |
| 完整备份 ZIP | RuntimeData SQLite 快照、受选项控制的 RuntimeData 文件、manifest 的成员/大小/digest；恢复前校验 | `library_export_service_export.py:212-345`、`library_export_service_validate.py` | 库根下原始资产已被复制进 ZIP（当前备份枚举的是 RuntimeData） |
| ZIP 恢复 | 关闭会话与 root reservation、staging 解压、quick_check、旧 RuntimeData 隔离、intent 标记、安装或回滚 | `library_export_service_restore.py:172-340`、`library_service.py:383-656` | 只因 DB 能打开就等同于业务投影完整 |

原始资产合同须明确为：备份/恢复**不复制**库根的图片、视频和其他资产文件；恢复后这些文件必须仍在同一 library root、字节 digest 不变。若产品要提供可迁移的“包含原始资产”备份，另立需求、格式版本和容量策略，不能暗中扩展当前 RuntimeData ZIP。

## 当前覆盖与缺口

已有 `tests/unit/test_library_export_service.py` 覆盖归档篡改、zip-slip、覆盖确认、staging/隔离/回滚、intent 和若干启动恢复；`tests/unit/test_library_service.py` 覆盖 marker/隔离候选和 admission。它们是必要基础，不替代下列组合合同。

W4 已在同一隔离运行域重做，且有正常恢复、被杀进程后旧态回滚、tag/备注/hero 评分和集合名称检查：`scripts/perf/w4_restore_drill.py:116-169,202-244,330-405`。但它遗漏或弱化：

- 未比较原始资产的内容 digest、目录/文件集合和路径编码；只检查 DB 大小与少数字段。
- 未覆盖评分 `0`、评分 `NULL`（未评分）以及恢复前目的库已有评分时的覆盖语义。
- 只确认集合名称，不确认普通集合成员、顺序/计数及 smart collection 的规则与重新求值。
- 未覆盖含中文、空格和字面 `%` 的路径；也未验证 manifest 内路径和恢复后 DB 投影的一致性。
- 中断点是第二次 replace 前，未覆盖损坏 ZIP、损坏 manifest/digest、无法写 staging/隔离/安装目标和恢复后源资产缺失的失败合同。

`build_metadata_export()` 当前仅从 `MetadataRepository.list_file_metadata()` 收集 notes/urls，再合并标签（`library_export_service_export.py:104-155`）；它没有 rating、favorites 或 collections。除非提升 JSON schema，否则测试必须把这些字段明确断言为“不在 JSON 合同内”，避免误把完整备份的数据库合同套到 JSON 导出。

## 可执行验收矩阵

所有行均在 `tmp_path` library + `AM_RUNTIME_ROOT` 隔离域中执行；每行保存 archive SHA-256、manifest、前后投影快照和失败后的 on-disk 状态。禁止用共享 RuntimeData 或真实资产目录。

| 场景 | 种子与动作 | 必须断言 |
|---|---|---|
| 正常完整备份/恢复 | 三个原始资产：`中文 50%/hero.png`、`普通/scene.txt`、`未评分/unrated.png`；对 RuntimeData 写 tags、notes、urls、rating 5/0/NULL、favorite、普通集合成员、smart collection | ZIP manifest/digest 校验；恢复后原始文件相对路径、SHA-256、字节完全相同；DB 中 tags/notes/urls、5、0、NULL 和 favorites 相同；集合成员、规则、evaluate 结果相同 |
| 元数据 JSON | 同一种子调用 `export_metadata_json` | JSON 只含稳定排序的 relative path/tags/notes/urls；中文与 `%` 不转义损坏；明确不含 rating/favorite/collection；目标替换原子 |
| 恢复覆盖语义 | archive 含 0/NULL/5；目的 RuntimeData 故意写不同 rating、集合成员、备注 | archive 状态成为权威；0 不被当 false，NULL 不回退为目的值；旧 RuntimeData 位于隔离区并可由 intent 恢复 |
| 中断回滚 | 在 quarantine→install 两次 replace 间杀子进程 | 新进程同 runtime root 自动恢复完整旧 RuntimeData；marker 消费；资产 digest 与旧投影快照相同；不产生空 DB |
| 损坏归档 | 截断 ZIP、改 manifest digest、重复/canonical-collision 成员 | 恢复在 mutation 前失败；目的 RuntimeData/资产 digest 不变；不建立错误 intent/隔离目录 |
| 不可写路径 | 分别使 staging 父目录、隔离区、install 目标不可写（Windows 用 monkeypatch/OSError 注入，避免 ACL 环境差异） | 操作失败且保留主异常与次级错误；旧数据不丢失；admission 状态符合 fail-closed/ACK 合同，重试路径可判定 |
| 源资产异常 | 恢复后删除或篡改 library root 原始文件 | DB 恢复不掩盖资产不完整：资产 digest 审计明确失败；不得报告“完整恢复成功” |

## 最小实施顺序

1. 在 `tests/unit/test_library_export_service.py` 增加复用 fixture：合成库、隔离运行域、原始资产 digest 清单，以及直接 SQL/服务层投影快照（tags、metadata/rating、favorites、collections/member/rules）。先写失败测试，不改格式。
2. 为现有 ZIP backup/restore 添加“完整投影 + 原始资产未触碰”回归；把 0 与 NULL 分成两个断言，避免 `COALESCE`/truthiness 假通过。
3. 单独增加 metadata JSON schema 边界测试；若产品要求 JSON 带 rating/收藏/集合，先升级 `SCHEMA_VERSION` 并写兼容读取策略，再实现字段扩展。
4. 扩展 `scripts/perf/w4_restore_drill.py` 或抽取无 UI 的验收 helper：使用上述快照、中文百分号路径、普通集合成员和 smart collection；归档 child/verify stdout、manifest 与 JSON verdict。脚本失败必须非零。
5. 将损坏和不可写矩阵保留在单元/集成测试中，以 OSError 注入稳定覆盖 Windows；仅将一个代表性中断场景保留给进程演练。
6. 通过相关测试后，生成一份只含合成库路径、commit、archive hash、矩阵结果和已知限制的证据报告；再决定是否更新 W4/W7 状态。

## 入口与完成判据

- 实现入口：`AssetsManager/application/library_export_service_export.py`、`library_export_service_validate.py`、`library_export_service_restore.py`、`library_service.py`；调用装配在 `application/bootstrap.py:718-723`。
- 回归入口：`tests/unit/test_library_export_service.py`、`tests/unit/test_library_service.py`；跨进程演练入口：`scripts/perf/w4_restore_drill.py`。
- N2 通过条件：每一矩阵行有可复核的成功或预期失败证据；成功行同时满足 DB 投影和原始资产合同；失败行不损坏旧 RuntimeData、不把异常降级为成功，也不依赖开发者机器的运行域。
