# 构建闭环整改方案（2026-09-02）

> 状态：**已执行完毕（2026-09-02 收尾）**——A：build.py 接入 webui_build + --skip-webui（commit ff1e0de）；B：setup_cython.py 删除 + ruff.toml 豁免移除 + clean_runtime.py 注记 + README 宣传清除（commit 见收尾提交）· 来源：第九轮 P1 整改项（`docs/reports/inventory-cross-verification-2026-09-02.md` 标记）。
> 工作模式：本文为**自包含交付物**，含 `file:line` 证据与可直接落地的代码片段，供其他 agent 执行。按既定协作约定，**本轮不修改 `build.py` / `AssetManager.spec` / `setup_cython.py` / `README.md` 本体**，仅产出方案。

## 0. 结论速览

| 子问题 | 性质 | 是否发布阻塞 | 推荐处置 |
|---|---|---|---|
| A. `webui/dist` 本地构建未编排 | 本地便利性缺口 | 否（CI 已覆盖） | **接入 `build.py`**：构建前自动 `npm run build` |
| B. `setup_cython.py` 孤立 | 死脚本 + 虚假性能声明 | 否 | **删除**脚本与 README 宣传；若想做原生加速则走"替代方案" |

两项均不影响已发布产物（release 流程在 `release.yml:45-49` 已先构建 WebUI），属**开发者体验与仓库卫生**问题，与 `outputs/`、并行会话 WIP 均无冲突。

---

## 1. 子问题 A：`webui/dist` 本地构建未编排

### 1.1 证据

- `build.py:21-26` 的 `build()` 仅执行 `PyInstaller AssetManager.spec --noconfirm`，**不产出 `webui/dist`、也不调用 `setup_cython.py`**。
- `AssetManager.spec:84` 将 `(webui/dist) -> webui/dist` 作为 datas 打包进产物。若源树中 `webui/dist` 不存在，PyInstaller 会因 datas 源缺失而报错，**本地 `python build.py` 无法直接产出可用包**。
- `AssetsManager/lan/routes/pages.py:7` 定义 `SPA_DIR = ... / "webui" / "dist"`；`:21` 在缺失时返回 `503 "WebUI/build is unavailable. Build the React WebUI before starting the LAN server."` ——源码态 LAN 同样依赖 `webui/dist`。
- 当前 `webui/dist` **未构建**（实测 `ls -d webui/dist` → NOT BUILT）。
- 发布链路**不缺**：`.github/workflows/release.yml:45-49` 在 `Build PyInstaller bundle`（`:55`）之前执行 `npm ci` + `npm run build`；`ci.yml:102-138/241-245/279-283/306-324` 多处同理。

### 1.2 影响

本地开发者执行 `python build.py`（或 `python build.py --build`）会失败或产出无 SPA 的包，必须**手动记忆**先 `cd webui && npm run build`。这是可逆的复现性纸老虎，但每次都踩。

### 1.3 整改（推荐）：在 `build.py` 增加 `webui_build()`

在 `build.py` 的 `build()` 前插入 SPA 构建步骤，使 `python build.py` 自包含：

```python
def webui_build():
    """构建 React/Vite SPA 至 webui/dist（供 AssetManager.spec:84 打包、
    lan/routes/pages.py:7 服务）。与 release.yml:45-49 的 CI 步骤保持一致。"""
    webui = ROOT / 'webui'
    if not (webui / 'package.json').exists():
        print('webui/ 不存在，跳过 SPA 构建。')
        return
    if not shutil.which('npm'):
        sys.exit('PATH 中未找到 npm，无法构建 WebUI SPA；请安装 Node 或手动构建 webui/dist。')
    subprocess.run(['npm', 'ci'], cwd=str(webui), check=True)
    subprocess.run(['npm', 'run', 'build'], cwd=str(webui), check=True)
```

并在 `build()` 中调用（置于 PyInstaller 之前）：

```python
def build():
    webui_build()                       # 新增
    result = subprocess.run(
        [sys.executable, '-m', 'PyInstaller', 'AssetManager.spec', '--noconfirm'],
        cwd=str(ROOT), capture_output=False)
    ...
```

可选：在 `__main__` 的 argparse 增加 `--skip-webui` 开关，供已预构建 `webui/dist` 的 CI/开发者跳过。

### 1.4 验证

```bash
rm -rf webui/dist && python build.py --clean --build   # 应自动构建 webui/dist 并产出可用包
# 源码态 LAN：python run.py 后访问根路径应返回 SPA 而非 503
```

---

## 2. 子问题 B：`setup_cython.py` 孤立（推荐删除）

### 2.1 证据

- `setup_cython.py:5-10` 编译 4 个热点模块为 `.pyd`（cache.py / color_utils.py / format_utils.py / application/asset_filters.py），目标模块**均仍存在**（`AssetsManager/core/cache.py` 等已确认存在）。
- 全仓检索 `setup_cython|cythonize`（排除 `.github/` 与 `docs/`）：仅出现在
  - `README.md:107`（文件清单列出）、`README.md:159`（`python setup_cython.py build_ext --inplace` 指令）
  - `ruff.toml:49`（`"setup_cython.py" = ["T201"]` lint 豁免）
  - `scripts/clean_runtime.py:74`（注释提及）
  - 以及历史分析文档
- **`build.py`、`AssetManager.spec`、CI 构建步骤均无调用**（`ci.yml:27`/`release.yml:26` 仅 `ruff check ... setup_cython.py` 做 lint，从不执行）。
- 即"Cython 2–5x 加速"声明**从未接入任何实际构建入口**——纯 Python 出货，速度声明未兑现。

### 2.2 影响

① 误导：README 宣传的加速契约不存在；② 死代码：脚本维护成本（Cython 版本兼容）无意义；③ 历史分析已多次标记（`docs/reports/project-analysis-2026-08-31.md` R11、U-16；`docs/full-review/10-native-acceleration-atlas.md`；`docs/plans/task-package-2026-09-01.md:262` 已给出"废弃则删，否则接通"的判定）。

### 2.3 整改（推荐）：删除死脚本 + 清理宣传

执行清单（建议其他 agent 执行，注意 `README.md` 当前为并行会话 WIP，须**避让其未提交改动**后再改）：

1. 删除 `setup_cython.py`。
2. `ruff.toml` 移除第 49 行 `"setup_cython.py" = ["T201"]`（连同其上下文注释）。
3. `README.md` 移除：`:107` 的 `setup_cython.py` 列举、`:159` 的 `python setup_cython.py build_ext --inplace` 整行，以及任何伴随的"Cython / 原生加速"性能声明。
4. `scripts/clean_runtime.py:74` 注释中"可经由 setup_cython.py 重建"改为说明该脚本已移除。

### 2.4 替代方案（若决定投资原生加速）

若产品需要原生加速，**不要直接 `cythonize` 宿主模块**。依据 `docs/full-review/10-native-acceleration-atlas.md:109-157`：

1. 先将 4 个模块中热点函数抽为**无状态叶子**（当前 `cache.py` 持有 `threading.RLock`，非理想 C 边界）；
2. 为叶子补**静态类型注解**（当前无类型，收益仅约 2–3x）；
3. 在 `build.py` 增加 `cython_build()`（门控于 `--cython` 开关，缺 Cython 时跳过），并在 `AssetManager.spec` 的 `hiddenimports` 增加对应 `.pyd` 条目；
4. 回归 `tests/performance` 验证真实加速倍数。

该路径工作量显著，且需先完成抽取/类型化前置，故**不作为本轮默认**。

---

## 3. 执行顺序与风险

1. **先做 A（低风险、高收益）**：纯增量步骤，不改变 CI/发布行为，仅补全本地闭环。
2. **B 的删除需避让并行会话**：`README.md` 现处 WIP（未提交），改 README 前先 `git status` 确认其已提交或合并，避免覆盖并行改动。建议等并行会话收尾后一并处理。
3. **回滚**：A 的改动若导致无 Node 环境构建失败，可用 `--skip-webui` 或 revert `webui_build()` 调用；B 删除为纯减项，git 可随时恢复。

## 4. 关联文档

- 发现登记：`docs/reports/inventory-cross-verification-2026-09-02.md`（P1 行）
- 历史分析：`docs/reports/project-analysis-2026-08-31.md` R11/U-16；`docs/full-review/10-native-acceleration-atlas.md`；`docs/plans/task-package-2026-09-01.md:262`
- 构建入口：`build.py`、`AssetManager.spec`、`setup_cython.py`、`.github/workflows/release.yml`、`AssetsManager/lan/routes/pages.py`
