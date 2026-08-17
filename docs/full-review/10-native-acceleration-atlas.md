# 可固定加速图谱（10-native-acceleration-atlas.md）

> 审查日期：2026-08-17 · 只读审查（未改生产代码）
> 范围：桌面浏览 / Gallery 投影 / LAN 搜索扫描 / 主题绘制 / 已有 Cython 四件套
> 基线：`master @ afd2d2b` + 工作区 S4 token 未提交改动
> 性质：**加速合同**，不是实施计划。模块未冻结前禁止按本图谱开工。

---

## 0. 一句话

这个项目值得加速的不是 `core/` 这个包，而是少数**无状态、高频、边界像 C 的叶子函数**。
现有四个 Cython 目标（`cache` / `color_utils` / `format_utils` / `asset_filters`）方向正确，但编的是整模块、未加 `cdef`，只是「可回退的原型」，还不是可固定的加速面。

---

## 1. 判定规则（四条同时成立才准入）

| # | 规则 | 过线标准 |
|---|---|---|
| 1 | **有测量** | 5–7 万文件库或 `PerformanceRecorder` 采样，该函数占该任务墙钟 ≥10%，且主要是 CPU，不是 I/O / 锁 / Qt |
| 2 | **边界像 C** | 入参是 `str` / `bytes` / `int` / `float` / 扁平 struct / 扩展名集合；不持有 `Connection`、不碰 Qt、不发事件、不做权限决策 |
| 3 | **调用极密** | 一次开库 / 一次 Gallery 全量 / 一次过滤排序会跑 ≥10⁵ 次，或滚动/绘制热路径每帧都走 |
| 4 | **语义冻结** | 签名、错误模型、大小写/分隔符/隐藏文件语义半年内不改 |

任一失败 → 停在 Python。I/O 外壳、会话对象、服务编排一律不准入。

**允许的形态（按升级成本）**

1. **加深现有 Cython**：`.py` 参考实现保留，热函数加 `cdef` / 静态类型，`.pyd` 可删可回退
2. **抽出 `native/` 纯函数包**：多个调用方共享同一组叶子函数，再编
3. **独立 C/DLL**：仅当出现感知哈希、重复文件、本地特征这类「从第一天就是原生」的新能力

禁止的形态：把 `core/`、`lan/server.py`、任何 `*Service`、任何 Qt 面板整层转写。

---

## 2. 任务 × 时间花在哪（先分清层）

墙钟和 CPU 不是一回事。加速只打第三列里带「CPU 循环」的格子。

```
用户任务                墙钟主因（先改 Python）              CPU 热循环（才考虑原生）
─────────────────       ──────────────────────────          ────────────────────────
进大目录 / 滚动网格     模型全量 reset、纹理重建、            自然排序 + 过滤谓词
                        目录 os.walk 风暴、watcher 刷新      （每条 entry 一次）
Gallery 首页 / 增量     全库 scandir + stat + 封面解码       扩展名判断、相对路径拼接、
                        + 投影落库                            前缀/父子路径、封面挑选排序
LAN 搜索 / quicksearch  全库 os.walk + 每文件 stat           文件名 substring / 大小写折叠
                        （scanner 无上限内存索引）            （索引已在内存后）
主题切换 / 图标绘制     QtSvg 栅格化 + 样式表重算            hex↔rgb、lighten/darken、alpha
切库 / 关窗             不可取消任务 + 无界等待              （无）
备份 / 恢复 / 商城      SQLite + 磁盘 + 状态机               （无）
```

桌面掉帧审查（`DeepSeek Docs/未来方向/07-桌面端性能优化计划.md`）已经定性：**主因是 reset / walk / watcher，不是解释器。** 缩略图解码已走 Qt/C++。本图谱不推翻那份结论，只把其中真正的 CPU 叶子钉死。

---

## 3. 分层总图

```
┌─────────────────────────────────────────────────────────────────┐
│  禁止加速（编排 / I/O / 生命周期 / 安全）                         │
│  database · migrations · schema · library_lock · workers         │
│  themes/icons 宿主 · plugins · lan/server · *Service · Qt 面板   │
└─────────────────────────────────────────────────────────────────┘
                │ 调用
                ▼
┌─────────────────────────────────────────────────────────────────┐
│  T0  已在编，加深即可（接口基本冻住）                              │
│  natural_key · filters_accept · format_size · hex/rgb/contrast   │
│  LRU get/set（可选）                                              │
└─────────────────────────────────────────────────────────────────┘
                │ 抽公共叶子
                ▼
┌─────────────────────────────────────────────────────────────────┐
│  T1  可固定，先抽纯函数再编（高密度、跨端共享）                    │
│  is_gallery_image · join_relpath · parent_relpath                │
│  normalize_relpath · casefold_contains · ext_of                  │
└─────────────────────────────────────────────────────────────────┘
                │ 测量过线后再动
                ▼
┌─────────────────────────────────────────────────────────────────┐
│  T2  候选，语义未完全冻 / 或收益取决于算法改写                    │
│  Gallery 封面挑选排序 · scanner 线性过滤 · 路径前缀集合查询       │
└─────────────────────────────────────────────────────────────────┘
                │ 产品能力出现后
                ▼
┌─────────────────────────────────────────────────────────────────┐
│  T3  未来能力，从第一天就可以是独立原生库                          │
│  感知哈希 / 重复文件 / 视频首帧（若不用 Qt）/ 本地特征向量         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. T0 — 已在编，加深即可

`setup_cython.py` 当前目标：

```
AssetsManager/core/cache.py
AssetsManager/core/color_utils.py
AssetsManager/core/format_utils.py
AssetsManager/application/asset_filters.py
```

这是正确原型：`.py` 保留、`.pyd` 可选、不改 API。问题是整文件 `cythonize()`，没有静态类型，收益停在约 2–3 倍；`cache.py` 还握着 `threading.RLock`，不是理想 C 边界。

### T0-1  浏览过滤 / 自然排序

| 函数 | 位置 | 调用方 | 密度 | 冻结度 |
|---|---|---|---|---|
| `natural_key` | `application/asset_filters.py:40` | 桌面 `_model` 排序、LAN `sort_key_for_entry`、Gallery 若干 `casefold` 排序可替换 | 每条可见 entry 至少 1–2 次；过滤/排序切换会重跑整表 | **高**。`file2 < file10`、按 `\d+` 切、数字段 `int`、其余 `lower` |
| `filters_accept` | `asset_filters.py:144` | 桌面 `FileSystemModel`、LAN `AssetService`（双端已对齐） | 每个 scandir 条目一次 | **高**。管线冻结：hidden → exclude → include_types → max_depth → search → category；目录恒过类型过滤 |
| `matches_search` | `asset_filters.py:113` | `filters_accept` 内 | 同上 | **高**。大小写不敏感子串 |
| `matches_exclude` | `asset_filters.py:125` | `filters_accept` 内 | 仅当设置了排除规则 | **中**。`fnmatch` + 去点二次匹配；规则集很小，不是第一优先 |
| `extension_matches_category` / `sort_key_for_entry` | `asset_filters.py:77,181` | 双端浏览 | 每条 entry | **高**。分类集合来自 `FILTER_CATEGORY_EXTS` + `IMAGE_EXTS` |
| `is_hidden` | `asset_filters.py:108` | 过滤管线、scanner 也有一份 `startswith(".")` | 每条 entry | **高**，但太薄；应并进 `filters_accept` 一起编，不要单独成模块 |
| `find_first_image` | `asset_filters.py:88` | 网格封面 | 每目录一次 + I/O | **不准入整函数**。I/O 留 Python；只加速「`suffix.lower() in IMAGE_EXTS`」这下判断 |

加深做法：给 `natural_key` / `filters_accept` 写 `cdef` 版，扩展名集合做成模块级 `frozenset`/`tuple` 常量（Gallery 热循环里不要再 `tuple(_SAFE_GALLERY_IMAGE_EXTS)`）。`.py` 测试继续当对照实现。

### T0-2  格式化 / 分类表

| 函数 | 位置 | 调用方 | 密度 | 冻结度 |
|---|---|---|---|---|
| `format_size` | `core/format_utils.py:4` | 桌面字幕、Gallery 节点、LAN 列表 | 每条可见文件 / 每个投影节点 | **高**。1024 进制、一位小数、单位阶梯 |
| `CATEGORY_MAP` | `format_utils.py:19` | `domain.asset.category_for_extension`、搜索结果分类 | 每条扫描/搜索命中 | **高**。表本身可冻；不要把 `category_for_extension` 的 domain 包装编进去 |

`format_size` 已在编，值得加 `cdef long long`。`CATEGORY_MAP` 保持一张表，不要在 Gallery / search / asset_filters 再复制一份。

### T0-3  颜色

| 函数 | 位置 | 调用方 | 密度 | 冻结度 |
|---|---|---|---|---|
| `_hex_to_rgb` / `_rgb_to_hex` | `core/color_utils.py:9,17` | `alpha` / `lighten` / `darken` / `contrast_*` | 主题切换、StyleKit、图标着色、Web token 生成对照 | **高** |
| `alpha` / `lighten` / `darken` | 同文件 | 桌面 QSS / 自绘 | 主题切换一次几百到几千次，不是每帧百万次 | **高**，但墙钟通常小于 Qt 栅格化 |
| `contrast_ratio` / `contrast_on` | 同文件 | 无障碍/标签前景 | 低 | 可顺手编，单独列项目不值 |

微基准里 3 倍是真的，但对「进大目录卡」几乎无感。定位是**主题/绘制微优化**，不要当成库级加速。

### T0-4  LRU（降级：可编，不作为核心层代表）

| 函数 | 位置 | 说明 |
|---|---|---|
| `LRUCache.get/set` | `core/cache.py:71-85` | 微基准 2.2–2.5x。内部 `RLock` + `OrderedDict`，不是 C 友好边界 |
| `TTLCache` | 同文件 | 还带 `time.time()` 过期，更不适合 |

建议：保留现有整模块编译当回退；**不要把 cache.py 宣传成「核心层 C 化」的样板**。若真要加深，只提纯字典 LRU（锁留在 Python 包装层）。

---

## 5. T1 — 可固定，先抽纯函数再编

这些函数今天散落在 Gallery / search / scanner / path 工具里，语义已经稳定，缺的是**抽到无状态叶子**。抽完之前不要直接 `cythonize` 宿主模块。

### T1-1  扩展名 / 媒体判断（全库热循环 #1）

| 建议函数 | 今天的写法 | 调用密度 | 为什么可冻 |
|---|---|---|---|
| `ext_lower(name) -> str` | `os.path.splitext(...)[1].lower()` 出现在 scanner、filters、search、Gallery | 每文件一次，Gallery 全量 7–15 万 | 语义就是「最后一段后缀，小写，带点」 |
| `is_image_ext(ext) -> bool` | `suffix.lower() in IMAGE_EXTS`（`domain/asset.py:79`、`find_first_image`） | 每文件 / 每封面候选 | `IMAGE_EXTS` 已收口到 `core/constants.py` |
| `is_gallery_image_name(name) -> bool` | `_aggregate_project`：`entry.name.lower().endswith(tuple(_SAFE_GALLERY_IMAGE_EXTS))`（`_projection_builder.py:291`） | **每个项目子树的每个文件** | `IMAGE_EXTS - {".svg"}` 已是产品决策；必须改成集合判断，禁止每次 `tuple(...)` |
| `is_video_ext(ext) -> bool` | `VIDEO_EXTS` | 视频首帧若落地 | 表已冻 |

这是整张图谱里**最该先抽**的一组。Gallery 深度审查 L 项已经点过「热循环每文件构建 tuple + `name.lower()`」。抽成 `native/media_ext.py`（或放进加深后的 `format_utils`）后，桌面扫描、LAN scanner、Gallery、搜索分类走同一实现。

### T1-2  库内相对路径（全库热循环 #2）

| 建议函数 | 今天的写法 | 调用密度 | 冻结点 |
|---|---|---|---|
| `normalize_relpath(text) -> str` | `Gallery._normalize_relative_path`（`_projection_builder.py:45`） | 每个公开入口 + 增量事件路径 | `/` 统一、去 `.`、拒 `..`、拒 NUL、空/`/`/`.` → `""` |
| `join_relpath(parent, name) -> str` | `"/".join(part for part in (rel, entry.name) if part)`（`:274`） | **每个可见条目** | 空父返回 name，禁止回退 `..` |
| `parent_relpath(rel) -> str \| None` | `_parent_path`（`:61`） | 每张图、每个增量 prune | 无 `/` → `""`，空输入 → `None` |
| `is_relpath_prefix(parent, child) -> bool` | 增量里用字符串前缀判断子树（`_incremental.py` 多处） | 每个 deleted/moved 事件 × 节点数 | 必须按路径段匹配（`parent == child or child.startswith(parent + "/")`），禁止裸 `startswith` |

注意：`domain.asset.assert_under_root` / `Path.resolve()` **不准入**。那是安全边界，依赖 OS 规范化与符号链接，必须留在 Python。原生层只处理**已经是库相对、`/` 分隔**的字符串。

`core/path_resolver.py` 里的 `root_identity` / `library_data_name` / `library_lock_path` 也不准入：一次开库用几次，还碰磁盘 marker 与哈希槽。

### T1-3  大小写折叠匹配

| 建议函数 | 今天的写法 | 调用密度 | 冻结点 |
|---|---|---|---|
| `casefold_contains(haystack, needle) -> bool` | `scanner.search`：`q in f["name"].lower()`（`lan/scanner.py:128`）；`matches_search` 同构 | 每次搜索 × 索引长度（可到 7 万+） | needle 空 → True；大小写不敏感子串 |
| `name_casefold(name) -> str` | Gallery `visible.sort(key=lambda item: item[0].name.casefold())`（`:234`）、封面列表 sort（`:295`） | 每目录一次 sort | 与 `str.casefold()` 对齐，不要自己发明 |

`scanner.search` 在索引已建成后是纯 CPU 线性扫。长期正解是 SQLite / FTS；在那之前，把 `casefold_contains` 编掉只能削一截解释器税，**不能替代换索引**。

---

## 6. T2 — 候选，先改算法，再谈语言

| 项 | 位置 | 为什么还不能固定 | 先做什么 |
|---|---|---|---|
| Gallery 增量「按路径找节点 / 扫 image_refs」 | `_incremental.py`（深度审查 M-G4：deleted/moved 对 refs 线性扫） | 结构是可变树 + dict，不是叶子函数 | 先加 `image_paths: set[str]` / 前缀索引，再考虑 set 的原生加速（通常不必） |
| `DirectoryScanner._scan_all` | `lan/scanner.py:62` | 墙钟在 `os.walk` + `os.stat`，不在 Python 循环体 | 取消、代际、预算已有；主解是复用 `assets` 表，内存索引降级 |
| `DirectoryScanner.search` 线性过滤 | `scanner.py:114` | 接口会随「切到 AssetIndex」消失或变 SQL | 先切索引；若过渡期仍要内存扫，只用 T1-3 |
| `_contained_relative_path` | `search_service.py:226` | 含 `resolve` / `commonpath` / 安全拒绝，属于防护 | 留 Python |
| `FileSystemModel._scan_signature` | `_model.py:257` | 每条 entry 几次 stat 字段打包，密度中等，语义绑模型 | 先保证增量 refresh 少 reset；不要为签名函数开 DLL |
| 网格 `natural_key` 之外的绘制 | `_grid_widget.py` | 已是 Qt 纹理 + 预算；Python 编排不是主因 | 继续增量模型 / 纹理按路径复用 |

T2 的共同特征：**换数据结构和减少工作量，比换语言有效一个数量级。**

---

## 7. T3 — 未来能力（出现时从第一天走原生）

这些今天不是产品主路径，不必预埋 DLL。一旦做，不要先写纯 Python 再「整体转写」：

| 能力 | 建议形态 | 不要放进 |
|---|---|---|
| 感知哈希 / 重复文件 | 独立 `native/phash`（或现成库绑定），输入字节块，输出 hash | `core/`、`file_operation_service` 本体 |
| 视频首帧 | 优先 Qt/`QImageReader`/外部工具；只有自研解码才上原生 | Gallery 投影服务 |
| 本地特征向量 / 以图搜图 | 独立进程或原生库，Python 只做编排 | `search_service` 里手写循环 |
| ZIP 打包 CRC / 压缩 | 已有标准库；不要自写 | `lan/routes/downloads.py` |

---

## 8. 明确禁止加速（避免再把 core 整层当靶子）

| 模块 / 类 | 原因 |
|---|---|
| `core/database.py`、`db_migrations.py`、`schema_defs.py` | I/O + 契约 + 迁移冻结，CPU 可忽略 |
| `core/library_lock.py`、`workers.py`、`crash_handler.py`、`timers.py` | 生命周期 / OS 锁 / Qt 线程 |
| `core/themes.py`、`icons.py`、`theme_loader.py` | QtSvg / QSS 宿主；颜色叶子已在 T0-3 |
| `core/plugins/**`、`application/plugin_service.py` | 动态加载、权限未冻 |
| `core/path_resolver.py` 的身份 / 槽位 / RuntimeData | 低频 + 磁盘 + 哈希 |
| `application/*_service.py`、`application/runtime.py`、`bootstrap.py` | 编排、会话、事件 |
| `application/gallery_service.py` 及三个 mixin **整文件** | 状态机、锁序、SQLite 持久化；只抽 T1 叶子 |
| `lan/server.py`、`lan/security.py`、`lan/path_guard.py` | 安全与生命周期；`PathGuard` 必须留 Python |
| `lan/scanner.py` **整类** | I/O 外壳；只抽 search 谓词 |
| `panels/**`、`window.py`、`widgets/**` | Qt 对象模型 |
| `repositories/**`、商城 / 订单 / 配额 | 正确性与 CAS，不是 CPU |
| WebUI / TypeScript | 不在本图谱；热路径在浏览器，不在 CPython |

`domain/asset.py` 的 `AssetPath` / `assert_under_root` 也不准入：值对象可以留着，安全 resolve 必须留在解释器能审的代码里。

---

## 9. 按任务的「先 Python、后原生」顺序

同一任务里，左边不做完，右边不准开工。

| 任务 | 先做（算法 / 产品） | 再做（本图谱） |
|---|---|---|
| 进大目录仍卡 | 增量模型、少 reset、目录大小单飞、watcher 防抖（07 性能计划 1–4 步） | T0-1 `natural_key` + `filters_accept` 加深 |
| Gallery 7 万库 30–60s | 封面软预算已有；再减每文件分配、取消令牌、项目 floor 语义保持 | T1-1 / T1-2 抽出后编；**禁止**编 `_build_node` |
| LAN 搜索慢 | `assets` 表主路径，scanner 降级为可选 | 过渡期 T1-3；不要给 `os.walk` 写 C |
| 主题切换略顿 | 图标 LRU 已有；QSS 单入口（D4） | T0-3 顺手加深，低优先级 |
| 切库冻结 | 取消令牌 + 专用池（D1 已开） | 无原生项 |

---

## 10. 目标形状（冻住之后）

```
presentation / application / domain     ← 永远 Python
        │
        ▼
AssetsManager/native/                   ← 唯一允许的加速面
    media_ext.py      # ext_lower, is_image_ext, is_gallery_image_name
    relpath.py        # normalize / join / parent / is_prefix
    text_match.py     # casefold_contains, name_casefold
    natural_sort.py   # 从 asset_filters 迁出的 cdef 实现
        │
        ▼
现有 .py 参考实现继续可跑；.pyd 可选
core/ 继续做装配、I/O、策略
```

短中期不必新建包：T0 继续留在原文件加深；T1 抽函数时**先放到 `application/asset_filters.py` 或 `core/format_utils.py`**（已在 Cython 名单里），避免第三套入口。等 T1 超过 4–5 个共享函数，再搬 `native/`。

工程纪律（沿用现有、补齐缺口）：

- `.py` 对照实现永远可跑；删除 `.pyd` 即回退
- 每个准入函数一份微基准 + 一份与纯 Python 的等价测试
- CI 要编过再测（现在 Cython 只在有 VS Build Tools 的本机发生，这是上 T1 的前置门禁）
- 三版本 Python（3.12/3.13/3.14）的 ABI 必须在门禁里，不能只编开发者的 3.14

---

## 11. 建议冻结清单（可当合同附录）

下面这些签名一旦写入 `native/` 或加深 Cython，视为冻结。改语义 = 新函数，不改旧函数。

```
natural_key(s: str) -> list          # 现有行为
filters_accept(name, is_dir, ...) -> bool
format_size(size: int) -> str        # 1024, 一位小数
ext_lower(name: str) -> str
is_image_ext(ext: str) -> bool
is_gallery_image_name(name: str) -> bool   # IMAGE_EXTS 去 .svg
normalize_relpath(text: str) -> str
join_relpath(parent: str, name: str) -> str
parent_relpath(rel: str) -> str | None
is_relpath_prefix(parent: str, child: str) -> bool
casefold_contains(haystack: str, needle: str) -> bool
```

不在此列的，默认不加速。

---

## 12. 结论

- **可固定的加速面很小**：浏览谓词、自然排序、体积格式化、颜色换算、扩展名判断、库相对路径、大小写子串。大约十来个函数，不是一层。
- **`core/` 整层不是靶子。** 它是 I/O 与策略外壳；里面真正像 C 的只有 `format_utils` / `color_utils` / 半个 `cache`。
- **Gallery / scanner / file_list 的宿主模块不可编。** 先抽 T1 叶子，墙钟大头继续用取消、预算、索引、少 reset 解决。
- **现在不要开工。** 本图谱是合同。接口未冻、CI 还不能复现 Cython 构建之前，保持现有四个可选 `.pyd` 即可。
