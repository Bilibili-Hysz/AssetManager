# Serpent 专业能力移植架构决策（2026-08-30）
> 状态：**现行**（分期实施） · 状态登记：2026-09-02（文档整理轮补登）


> 目标：把 Serpent 的专业深度（RAW/EXR/PSD 解码、序列帧、音频波形、主色派生）与有效功能（合集/智能合集、FTS5 全文、评分）移植进 AssetManager 的 Python 代码库。
> 本文是**架构决策**，实施按 §五 分期。已验证事实：本机 SQLite 3.50.4 含 FTS5（虚表可用）；rawpy/psd-tools 未装（按可选依赖设计）。

---

## 一、总原则：六个嫁接点，全部复用现有骨架

不引入新框架、不新增进程。每个能力都落在 AssetManager 既有的一个架构缝上：

| # | 能力 | 嫁接点 | 判据 |
|---|---|---|---|
| 1 | 派生物登记 | **新表 `asset_derivatives`**（迁移 v37）+ 库数据目录 `data_dir/derivatives/<kind>/` | 既有 thumbnail_cache 是"可丢缓存"（FIFO 逐出），Serpent 的专业深度本质是"资产履历"（登记可再生的正式派生物）。两者语义不同，**不合并**——缓存继续管缩略图热路径，履历表登记 viewer_image/poster/waveform/palette/sequence_manifest 等新种类 |
| 2 | 专业格式解码 | **application/media/ 解码器注册表**：`MediaDecoder` Protocol（`extensions()` / `decode(path) -> PIL.Image`）+ 注册表按扩展名路由；Pillow 兜底 | RAW（rawpy）、PSD（psd-tools）、EXR（OpenImageIO/exiftool 兜底元数据）都是可选 pip 依赖——逐个 `find_spec` 探测注册，缺失即回退图标+日志，核心安装保持轻。放 application 层是因为 core 不得引入可选依赖；缩略图管线（panels/file_list/_loader.py）与 LAN 缩略图路由经 runtime services 注入注册表（沿用 TagStore `install_repository_factory` 的接缝模式），core 零改动 |
| 3 | 序列帧 | `application/sequence_service.py`：扫描期识别（同目录同前缀+连续帧号 ≥3 归组）→ `asset_sequences`/`asset_sequence_frames` 表（v37）+ manifest 派生物；桌面 ImageViewer 加序列播放模式；LAN/Web 列表以单卡代表 | 纯 Python 正则分组即可，无需 Serpent 的离屏渲染栈 |
| 4 | 合集/智能合集 | 完全照既有仓储模式：`collections`/`collection_assets`/`smart_collections` 三表（v38）+ `collection_repository.py` + `collection_service.py`（发布 collection_changed 领域事件入 RuntimeEventRouter）+ LAN routes（route_policy 能力位复用 browse）+ webui 页面 + 桌面 sidebar 分组 | 这是最"像现有代码"的一个：TagService/TagRepository 就是模板。智能合集存结构化查询 JSON（序列化 T7 的谓词集：name/ext/size/mtime/tags），**必须是查询视图，绝不物理移动文件**（上游方案铁律 §5.4） |
| 5 | FTS5 全文 | `asset_search` FTS5 虚表 + **触发器维护**（file_tags/notes/file_meta 变更同事务更新，照 Serpent "同事务、非 best-effort" 模式）；`application/search_syntax.py` 纯函数解析器（AND/OR/`-`排除/引号短语/`name: tag: notes:` 字段限定）；接入三源搜索为第四源 | FTS5 本机可用已验证；触发器属于迁移 SQL 的一部分（v38/v39），符合"迁移只加步骤"纪律 |
| 6 | 评分 | `file_meta` 加 `rating INTEGER` 列（v37 顺带）+ LAN/desktop 信息面板 + 过滤维度 | 10 分钟级小改，但解锁"按评分过滤/排序"的专业习惯 |

**可选依赖策略**：新增 `requirements-media.txt`（rawpy、psd-tools、（评估中）OpenImageIO），主 requirements 不动；CI 矩阵加一个"装了媒体extras"的 job 变体，保证两条路径都被测试覆盖（缺依赖=回退路径也要有测试）。

## 二、为什么不是另外三种方案

- **否决"扩表到 thumbnail_cache"**：把 viewer_image/poster 等塞进缓存表会让 90 天/逐出语义误伤正式派生物，且缓存表无 kind 白名单——履历必须一等公民化。
- **否决"独立媒体微服务/新进程"**：Serpent 的多进程是为 Electron IPC 沙箱服务的；我们单进程+线程池已经覆盖（ffmpeg 池先例），加进程只增加序列化与调试成本。
- **否决"先做 3D 查看器"**：桌面 GL 三维查看是数周级工程且与现有 ImageViewer 架构不接；Web 端 three.js 版本（LAN 静态派生物已可服务）留作后续独立评估。第一波专业深度以"看得见"（RAW/EXR/PSD 缩略图+查看）为主。

## 三、明确不搬的 Serpent 部件

离屏 BrowserWindow 缩略图、Inno Setup/自研更新器、多进程 Worker 模型、7 lane 准入（单连接下无意义，T10 决策前不做）、sync_id/WebDAV（上游铁律：不自建同步）、Eagle/Billfish 迁移（候选项，未排期）。

## 四、事件与门禁接线（每个能力都要过的关）

1. **迁移**：全部进 v37（derivatives + sequences + rating）与 v38（collections 三表 + FTS 虚表+触发器）——追加步骤、SCHEMA_OBJECT_CONTRACT 条目、frozen history 追加、SAVEPOINT 不动。
2. **事件**：派生物生成/序列识别 → RuntimeEventRouter 失效（WS 自动推送 Web）；合集变更 → 新领域事件（第 17 个）。
3. **权限**：新 LAN 路由复用能力位（合集= browse 读 + manage_links 写？或新增 collection 位——实施时按 route_policy 现状定）。
4. **静态门禁**：新代码过 check_layers/boundaries/style_sources/doc_stats；i18n 三语同步。
5. **测试**：迁移幂等/契约、解码器注册表缺依赖回退、序列识别边界（1-2 帧不算）、FTS 语法解析器全表、合集查询视图不移动文件。

## 五、分期（每期 ≤1 个执行代理日）

| 期 | 内容 | 依赖 |
|---|---|---|
| **N-A 地基** | v37 迁移：asset_derivatives + asset_sequences(+frames) + file_meta.rating；派生物写入 API（application/media/derivatives.py） | 无 |
| **N-B 解码器** | application/media 注册表 + rawpy/psd-tools 接入 + 缩略图/查看/LAN 三处消费 + waveform/palette 派生 | N-A；requirements-media.txt |
| **N-C 序列帧** | 识别服务 + 表接入 + 桌面序列播放 + Web 单卡代表 | N-A |
| **N-D 合集** | 三表 + 服务/仓储/事件 + LAN + webui + 桌面 sidebar | 无（可并行） |
| **N-E FTS 全文** | 虚表+触发器迁移 + search_syntax 解析器 + 第四源接入（桌面高级面板/Web q 透传语法） | N-A |
| **N-F 后续评估** | MCP 暴露、流式 ZIP、gitignore、3D Web 查看器、任务租约 | 独立立项 |

**建议开工序**：N-A → N-B → N-D → N-C → N-E（N-D 不依赖媒体栈，可提前插入）。
