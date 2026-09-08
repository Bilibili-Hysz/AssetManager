# N3 ZIP 饱和 / quota 时序 + thumbnail 变化/容量边界 执行小结（子代理续做线，2026-09-08）

## 运行环境

- 快照：`.pytest-tmp-lead-snapshots/n3-lan-ops`（gitignore 子树，与主工作区生产代码零共享写路径）
- 快照 HEAD：`9f6d20c`（含工作包基线 `e3a908e` 与前序 N3 交付 `test_zip_cancel_ownership_loop.py`）；本轮仅新增两个测试文件，生产代码改动 **0**，无 git commit/push
- 运行命令（快照内执行；`-o addopts=''` 关闭 xdist，串行）：
  `QT_QPA_PLATFORM=offscreen python -m pytest -v -o addopts='' -p no:cacheprovider --junitxml=artifacts/n3-sat-thumb.xml tests/lan/test_zip_saturation_quota_timing.py tests/lan/test_thumbnail_policy_capacity.py tests/lan/test_zip_cancel_ownership_loop.py`
- 结果：**8 passed / 0 failed / 0 error，7.71s**（新 6 + 既有回归 2；此前重复运行 6 轮均全绿，无时序脆弱）
- 主工作区改动：仅本目录 `n3-sat-thumb.xml`、`n3-sat-thumb-output.txt`、`n3-sat-thumb-summary.md` 三个证据文件
- 新测试文件（均在快照内）：
  - `tests/lan/test_zip_saturation_quota_timing.py`（组 A，2 用例）
  - `tests/lan/test_thumbnail_policy_capacity.py`（组 B，4 用例）
- 手法：全部真实 HTTP（`TestClient/TestServer` + `_make_lan_app` 组合应用，未 mock 路由内部）；复用既有 harness 注入点——`TemporaryFileResponse.prepare` 门控与 `tempfile.mkstemp` 跟踪（沿 N3 所有权闭环线）、缓存 artifact 预置（沿 `test_thumbnail_admission`）、`AppSettings.instance` 缝合与显式签名 cookie（沿 `test_free_download_quota`）；匿名身份用 `DummyCookieJar` + 显式 `Cookie` 头，身份确定性不受 jar 行为影响

## 断言组状态表

| 组 | 断言点 | 状态 | 证据（junitxml 用例） |
|----|--------|------|----------------------|
| A1 | `max_jobs=1` 注入 + prepare 阻塞：第二请求 503 + `Retry-After: 1` + `zip_capacity_exhausted`，不建第二 ZIP（mkstemp 计数仍 1）、不 prepare 第二响应 | PASS | `test_zip_saturation_denies_second_job_without_zip_or_quota_cost` |
| A2 | 预算前/中/后三份 snapshot 钉死时序：前 `{0,0}` → 中 `{1, 512MiB}` 且 `try_acquire() is None` → 后 `{0,0}`（首个 archive 删除、reservation 释放后） | PASS | 同上 |
| A3 | 放行时序：门控释放 → 首响应 200、成员名/字节逐点核对 → 预算归零 → 第二 job 经真实请求合法获准并成功（恰新建 1 个 archive） | PASS | 同上 |
| A4 | quota 时序/竞争：授权 job 消费发生在 prepare 之前（阻塞期 used=1）；503 前后 quota 窗口逐字段相等；匿名 cookie 与 authenticated principal 并发竞争同一资源——成功数不超限、拒绝全为 429、`used == 成功数`（无误记消费）、顺序恢复由窗口状态唯一决定 | PASS | `test_quota_race_between_anonymous_cookie_and_authenticated_principal` |
| B1 | cache miss → hit → 304 序列：miss 200 `image/webp` + `private, no-cache` + nosniff + 弱 ETag、正文 == 源图独立参照渲染；hit 200、正文 == artifact 独立参照渲染（≠ miss 正文）；hit ETag 条件请求 304 + 空 body + cache 头保活 | PASS | `test_thumbnail_cache_miss_then_hit_sequence_pins_headers` |
| B2 | blur 翻转（真实 tag 库 + `blur_tags`）：翻转后无条件请求 200 `private, no-store`、无 ETag、正文 == 模糊参照渲染（≠ 旧未模糊正文）；带旧 ETag 的条件请求**绝不 304**、正文 == 翻转后模糊正文 | PASS | `test_blur_policy_flip_never_returns_stale_unblurred_body` |
| B3 | 缓存未模糊 artifact + 翻转：cache hit 在翻转后重解析为 should_blur=True，服务端重渲染模糊版——旧未模糊正文与其原始 artifact 字节均不外发；旧 ETag 不可复活未模糊表示 | PASS | `test_blur_tightening_after_cache_hit_never_serves_cached_unblurred_body` |
| B4 | 64 MiB 临界：`MAX+1` 字节 → 413 `payload_too_large`（`source_bytes`/`limit_bytes` 逐点）；恰好 64 MiB 的有效 PNG（噪声 PNG + IEND 后零填充到精确字节）→ 200 `image/webp`、解码为 WEBP 且 max dim ≤ 128；超限失败后 `thumbnail_dir` 无 artifact、`list_cache_metadata` 为空，后续合法请求仍 200 | PASS | `test_thumbnail_source_limit_boundary_keeps_cache_clean` |
| 回归 | 取消 ZIP 所有权闭环（前序交付，两用例）未被弱化 | PASS | `test_cancelled_batch_zip_ownership_loop`、`test_identity_change_keeps_ownership_and_spares_replacement` |

## 与实际合同的差异清单（按实际行为钉死，非臆测）

1. **quota 并发 CAS 的 `rate_limited` 时序噪声（如实记录，非泄露类缺陷）**：`FreeDownloadQuotaService.consume` 在获取连接写锁**之前**采样 `now`；`min_interval_seconds=0` 时，排队线程的 `now` 可早于前一位赢家的 `last_download_at`，CAS `(last_download_at <= now)` 落败进入兜底分支 → 以 `reason=rate_limited`（429 `download_rate_limited`）拒绝，且 `remaining > 0`。因此并发下"每身份恰好 limit 次成功"**不成立**（时序依赖）；成立并已被钉死的硬边界是：成功数 ≤ limit、首个消费必成功、拒绝全为 429、`X-Quota-Remaining` 与 body `details.quota.remaining` 一致、终态 `used == 成功数`（拒绝零误记）、顺序恢复由窗口状态唯一决定（`used<limit` → 200 且 used+1；`used==limit` → exhausted 429）。行为是 fail-closed 的，不构成超限/误记泄露，故按合同钉死而非停组；若产品后续把 `now` 采样移入写锁内，本测试无需改动（不变式仍然成立）。
2. **503 分支的覆盖归属**：quota store 不可用 → 503 `service_unavailable` 且不误记消费的分支，由既有 `test_free_download_quota.py` 覆盖（目录/批量 503 均清理已建 ZIP），本组未重复实现；本组 503 覆盖的是 ZIP 容量饱和路径。
3. **LAN 缩略图路由从不写 `.webp` 磁盘缓存**（缓存写入在桌面端 `panels/file_list/_loader.py`）：cache hit 只能通过预置有效 artifact（既有 admission 手法）达成；B4 把"按需路由不污染缓存/元数据"顺势钉死（`thumbnail_dir` 恒空 + 元数据零行）。
4. **纯色源模糊不可区分**：`GaussianBlur(15)` 对均匀色图像产生相同字节（2x2 白图 / 纯绿 WEBP 均如此），blur 断言必须使用结构化（噪声）源——测试设计约束，非产品问题。
5. **size≥256 未模糊 miss 走原图直发 fast path**（`raw_candidate` + `inspect_raster_bytes`）：本组统一用 `size=128` 处理路径钉 headers/正文，避免与该既有合同纠缠；未弱化 `test_thumbnail_admission` 已钉合同。
6. **`process_image_bytes` 返回 `(bytes, content_type)` 二元组**：正文等值参照断言取 `[0]`（首版误当纯 bytes，已修正）。

## 独占测量矩阵剩余建议（第 3 步 W5 probe 尚未实施）

- 矩阵行覆盖状态：`ZIP 并发饱和`、`quota 竞争`、`thumbnail 变化/压力` 三行的**语义钉死**已由本轮完成；`c1 基线`、`c8 混合`、`慢读取消`、`清理 OS 失败` 四行仍只有单测级覆盖，专属 probe（wall/p50/p95/RSS/lag 采样、JSON 归档、digest 摘要）待第 3 步扩展。
- ZIP 饱和行 probe 建议：采样 `Retry-After` 值、prepare 阻塞时长分布、budget 三点快照序列、quota 窗口差值（语义已钉，probe 只补数字，勿固化为 SLA）。
- thumbnail 行 probe 建议：补 RSS/lag 与 miss/hit 耗时采样点；本轮只钉 status/content-type/cache 头/字节语义。
- quota 竞争行 probe：直接复用本 harness 时注意差异清单第 1 条——按 `used == 成功数` 与"成功数 ≤ limit"钉结果，勿把单次成功数当常量。
- 64 MiB 临界用例每轮生成 ~64 MiB 临时文件（12.6 MB 噪声 PNG + 零填充），单用例约 2–3 s；probe 化时留意磁盘与时长预算。
