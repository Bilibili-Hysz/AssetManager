# 真实图片 IO / 目录性能基准协议

状态：协议入口已提供；当前报告不代表已完成发布机实测。

## 目的与边界

本协议补齐桌面端性能计划中“真实图片 IO 与发布机复测待测量”的证据入口。它只测量用户明确提供的真实图片数据集，不生成合成图片，不改写数据集，也不修改 AssetsManager 生产代码、FileList 或 WebUI。

结果是可重复的本地趋势证据，不是机器无关的 CI 阻断门禁，也不能单独把结果转化为发布阈值。

## 执行入口

```powershell
python -m tests.perf.real_io_directory_benchmark `
  --dataset-root "H:\\path\\to\\real-images" `
  --dataset-id "<stable-dataset-id>" `
  --dataset-version "<capture-or-version>" `
  --sample-size 64 `
  --repeats 5 `
  --storage-description "<local SSD / network share / ...>" `
  --output-dir artifacts/perf/real-io-directory
```

成功后，时间戳目录内包含：

- `manifest.json`：按相对路径排序、包含文件大小与 SHA-256 的稳定 manifest，以及固定采样结果；
- `real-io-directory.json`：完整环境元数据、协议参数、原始重复耗时与 P50/P95；
- `real-io-directory.md`：便于评审和归档的摘要报告。

若未提供真实图片目录，或目录中没有支持的图片文件，入口会失败并明确提示；不会回退到合成 fixture。

## 固定性要求

每次可比运行必须保持以下字段一致或显式说明变化：

1. dataset ID 和 dataset version；
2. manifest SHA-256；
3. sampling seed、sample size；
4. 图片扩展名集合、重复次数（固定为 5）；
5. 存储上下文、硬件元数据与 Python 版本。

采样不是随机抽样：入口按 `dataset-id + dataset-version + seed + relative path` 的 SHA-256 排序，取前 N 项，因此同一 manifest 下可重现。

## 测量协议

每个场景执行 5 次：

- `cold`：不做进程内预读后开始计时；这只是 best-effort 的首次访问条件，入口不尝试刷新或驱逐操作系统文件缓存；
- `warm`：先做一次不计时的进程内预读，再执行 5 次计时重复。

每次重复包含两个操作：

- `image_read_bytes`：逐个打开固定采样图片并读取全部字节；manifest 生成与 SHA-256 校验在计时外完成；
- `directory_recursive_scan`：递归扫描真实数据集目录，统计文件总数和图片文件数。

对 5 次重复耗时报告 `min / P50 / P95 / max`。P50/P95 只在同一场景、同一操作、同一固定样本内计算，不跨机器或跨 dataset 汇总。

## 硬件与结果记录

JSON 中至少记录：操作系统、版本、机器架构、处理器字符串、CPU 逻辑核数、Python 版本、运行卷可用空间、存储描述、dataset ID/version、manifest SHA-256、采样 seed/size 和重复次数。

建议发布机复测时同时记录：电源模式、后台扫描/同步软件、网络盘挂载方式、是否刚重启、是否存在系统级文件缓存影响。入口不会把这些不可控因素伪装成精确的 cold cache 事实。

## 结果解释与阻塞条件

以下情况只能标记为“阻塞/不可比较”，不能用猜测补齐：

- 没有可读取的真实图片数据集；
- dataset version 或 manifest 发生变化但未重新建立基线；
- 无法确认存储上下文，或运行中有明显后台 IO 干扰；
- 只能得到合成图片、零字节占位文件或不完整采样。

本协议不设置硬编码性能阈值，不让结果直接失败 CI。后续如要建立发布门槛，应由单独决策记录定义目标硬件、数据集、允许波动范围、重复策略和失败处理，并保留原始 JSON 证据。
