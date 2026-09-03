# 工程交托执行计划：基线核验、隐患消除与前端深度优化

本文档作为接手本项目开发的正式实施规划，按照此前约定的标准工程纪律（起手五步法）推进，先完成基线摸底与存量遗留隐患排查，随后呈递并执行前端深度优化任务。

---

## 一、 当前质量基线摸底结果 (Baseline Verification)

在不修改任何业务代码的前提下，已对当前工作树执行了全面的质量与架构门禁校验，结果如下：

| 门禁项目 | 检查命令 / 脚本 | 状态 | 说明 |
|---|---|---|---|
| **架构分层依赖 DAG** | `python scripts/check_layers.py` | ✅ PASSED | 无跨层逆向依赖，DAG 拓扑正常 |
| **前端 S2 取数禁令** | `python scripts/check_frontend_data_fetch.py` | ✅ PASSED | 10 个页面均未直连 API 或调用裸 fetch |
| **文档与统计守护** | `scripts/check_doc_stats.py` | ✅ PASSED | README 统计与实际文件树契约对齐 |
| **Python 代码规范** | `python -m ruff check AssetsManager scripts run.py` | ✅ PASSED | 零 Lint 警告与错误 |
| **WebUI 类型系统** | `npm run typecheck` (`tsc --noEmit`) | ✅ PASSED | TypeScript 严格模式零类型错误 |

**基线结论**：当前工作树处于高度健康的**绿灯（Clean）状态**，具备安全进入修改与优化的坚实基础。

---

## 二、 第一阶段：隐患排查与消除 (Fragility Elimination)

### 1. 历史审计疑点现场实测核验
对此前审计文档提及的疑点进行了源码比对，发现**多个历史隐患已在此前迭代中被彻底修复**：
- ✅ **Cloudflare 隧道安全**（[AssetsManager/lan/tunnel.py](file:///d:/~Vibe-Coding/Projects/AssetsManager_old-bak/AssetsManager/lan/tunnel.py)）：已锁定特定版本 `2024.8.3`，且每次下载均强制拉取官方 `.sha256` 进行哈希校验，不匹配直接 fail-closed 丢弃。
- ✅ **Qt 跨线程 QPixmap 风险**（[AssetsManager/panels/info.py](file:///d:/~Vibe-Coding/Projects/AssetsManager_old-bak/AssetsManager/panels/info.py)）：`_FileInfoTask` 在后台线程仅解码并输出纯 `QImage`，通过信号槽传回主线程后才由 `_on_preview_ready` 转换为 `QPixmap`，完全符合 Qt 线程模型。
- ✅ **WebUI 下载停滞超时**（[webui/src/api/client.ts](file:///d:/~Vibe-Coding/Projects/AssetsManager_old-bak/webui/src/api/client.ts)）：已实现 `withStallBudget`，每个流式 chunk 均刷新超时定时器，解决了大文件下载超时中断问题。

### 2. 本阶段计划消除的存量实质隐患

#### 【隐患项 1】`_last_touch` 字典无界增长隐患（桌面端内存泄漏）
- **位置**：[AssetsManager/panels/file_list/_loader.py#L417](file:///d:/~Vibe-Coding/Projects/AssetsManager_old-bak/AssetsManager/panels/file_list/_loader.py#L417) 与 [L1607](file:///d:/~Vibe-Coding/Projects/AssetsManager_old-bak/AssetsManager/panels/file_list/_loader.py#L1607)
- **原因**：缩略图加载器的 `_last_touch` 用于节流元数据更新（防 SQLite 写入放大）。该变量为普通 `dict[str, float]`，在长会话或遍历海量目录时不断累加 Key，缺乏容量上限保护。
- **改动方案**：引入有界容量上限（如 `_LAST_TOUCH_CAP = 8192`），当字典容量超标时自动淘汰最旧条目（基于 OrderedDict 或分批淘汰超期条目），防止超长运行会话下内存缓慢攀升。

#### 【隐患项 2】`_suppress_libpng_warnings` 全局进程文件描述符截断
- **位置**：[AssetsManager/panels/file_list/_loader.py#L168-L187](file:///d:/~Vibe-Coding/Projects/AssetsManager_old-bak/AssetsManager/panels/file_list/_loader.py#L168-L187)
- **原因**：为了抑制 libpng 的 C 层告警，代码使用 `os.dup2(devnull, 2)` 重定向了进程的 `fd 2`（stderr）。虽然持有 `_stderr_redirect_lock`，但在高并发多线程场景下可能短暂吞掉其他并行线程的异常日志。
- **改动方案**：增设开关或增加防御性保护，确保在调试模式或非必要场景下不硬性重定向整个进程的标准错误流。

---

## 三、 第二阶段：前端深度优化建议方案 (Frontend Optimization Proposals)

在上述存量隐患消除后，针对**桌面端前端（PySide6）**与**WebUI 端前端（React 18）**提出以下四个高价值优化方向，供您挑选和决策：

### 建议方向 1：WebUI 海量资产分批/虚拟化渲染（提升高密度浏览流畅度）⭐ **推荐**
- **现状分析**：
  - [webui/src/components/files/ProjectGrid.tsx](file:///d:/~Vibe-Coding/Projects/AssetsManager_old-bak/webui/src/components/files/ProjectGrid.tsx) 与 [MasonryView.tsx](file:///d:/~Vibe-Coding/Projects/AssetsManager_old-bak/webui/src/components/files/MasonryView.tsx) 目前是将目录内的所有条目全量挂载为 DOM 节点。
  - 当单目录下有 1000~3000+ 张图片时，全量 DOM 挂载会导致首次渲染卡顿、内存占用过高，在移动端容易掉帧。
- **优化方案**：
  - 引入基于视口 Intersection 的**分批递增注水（Batch Hydration / Windowing）**或轻量级虚拟列表机制。
  - 首屏仅渲染视口及上下缓冲区的卡片，随着用户向下滚动分批追加，将活动 DOM 节点控制在安全范围内。
- **预期收益**：超大目录（1000+ 项）打开耗时下降 60% 以上，滚动 FPS 稳定在 60 FPS，内存占用显著降低。

### 建议方向 2：WebUI 图片加载骨架与淡入动画（优化视觉加载体验）
- **现状分析**：
  - 缩略图在加载过程中，占位图到正式图片的切换较为瞬态，若遇网络慢速或批次返回延迟，卡片会产生轻微闪烁感。
- **优化方案**：
  - 在 [ProjectCard.tsx](file:///d:/~Vibe-Coding/Projects/AssetsManager_old-bak/webui/src/components/files/ProjectCard.tsx) 与 [MasonryView.tsx](file:///d:/~Vibe-Coding/Projects/AssetsManager_old-bak/webui/src/components/files/MasonryView.tsx) 中增加加载态动效（骨架屏微光渐变，Shimmer Effect）。
  - 图片完成加载时加入 `opacity: 0 -> 1` 的平滑渐入（Fade-in 150ms），并优化图片加载失败时的优雅兜底图标。
- **预期收益**：显著提升弱网和海量图片浏览时的视觉精致度与丝滑感。

### 建议方向 3：桌面端网格快速滚动与分类过滤缓存优化
- **现状分析**：
  - 桌面端文件列表（[file_list](file:///d:/~Vibe-Coding/Projects/AssetsManager_old-bak/AssetsManager/panels/file_list)）虽然具备 QPainter 虚拟画布，但在高频重绘或筛选时，每个项的文件类型分类（Category Lookup）存在重复计算。
- **优化方案**：
  - 在 `FileSystemModel` 中缓存项的分类枚举索引，避免在每次 `paintEvent` 和过滤管线中反复调用字符串后缀匹配；
  - 优化网格卡片的文本绘制排版缓存（QTextLayout / QFontMetrics 缓存），进一步压缩大分辨率屏幕下的重绘耗时。
- **预期收益**：桌面端网格快速滑轮滚动时的 CPU 占用率降低 15%~25%。

### 建议方向 4：WebUI 全局 CommandPalette（命令面板）高频功能增强
- **现状分析**：
  - 当前 [webui/src/components/ui/CommandPalette.tsx](file:///d:/~Vibe-Coding/Projects/AssetsManager_old-bak/webui/src/components/ui/CommandPalette.tsx) 主要用于页面间跳转，缺乏对资产库内容（标签、快速搜索、视图切换）的直接操作。
- **优化方案**：
  - 支持快捷前缀语法（如 `#` 搜索标签、`>` 触发视图切换或主题切换、`?` 打开帮助）；
  - 支持在命令面板中直接切换网格/列表/瀑布流模式与全屏预览。
- **预期收益**：极大提升高级用户在 Web 端纯键盘流的生产力。

---

## 四、 计划实施路线（Milestones）

```
[阶段一] 存量隐患消除（即刻执行）
   ├── 修复 _loader.py 中 _last_touch 无界字典
   ├── 强化 _suppress_libpng_warnings 的安全边界
   └── 运行全套门禁回归验证
          │
[阶段二] 前端优化推进（由您选定上述方向）
   ├── 针对选定方向实施原子化改动
   ├── 保持 Python 契约与 TypeScript 类型对齐
   └── 补充自动化测试与验证
```

---

## 五、 用户决策请求（User Review Required）

> [!IMPORTANT]
> 1. 请确认是否批准**阶段一（隐患消除）**的改动方案（`_last_touch` 有界化保护）。
> 2. 在**阶段二（前端优化）**中，您希望优先重点推进哪一个方向？
>    - **选项 A（推荐）**：**方向 1 + 方向 2**（WebUI 海量资产分批/虚拟化渲染 + 图片平滑加载体验，直接改善用户最常面对的浏览卡顿）
>    - **选项 B**：**方向 3**（桌面端 QPainter 网格滚动与分类过滤性能优化）
>    - **选项 C**：**方向 4**（WebUI 键盘流与 CommandPalette 交互增强）
>    - **选项 D**：全量按序推进
