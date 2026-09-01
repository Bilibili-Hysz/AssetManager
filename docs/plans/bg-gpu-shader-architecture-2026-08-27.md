# 背景渲染新架构:GPU 着色器 / 视频 / Shadertoy 程序化背景(2026-08-27,设计稿)

> **updated**: 2026-08-27
> **状态**:设计定稿待实施;M1(CPU 默认路径)已于 2026-08-27 完成并提交。
> **范围**:`docs/full-review/**` 不涉及。本文是 LIVING 与证据文化下的实施蓝图,每步落地必须伴随
> commit + 命令 + 平台 + 版本 + digest 的 dated 证据。

> **范围收窄（2026-08-28）**：经 `bg-simplify-image-only-2026-08-28.md` 决策,背景**源**收敛为单张静态图片,移除视频背景与"着色器作为背景类型";滤镜**特效层**保留并着色器化(`none/blur/mosaic/kuwahara/shader`)。即本文 §0 目标第 2 条"视频背景"与第 3 条"Shadertoy 程序化**背景**"已收窄为:视频背景**不做**,Shadertoy 片段仅作图片滤镜特效层(`iChannel0=图片`)。背景架构仍以本文为准;`bg-simplify-image-only-2026-08-28.md` 已于 2026-09-02 收敛轮并入本文并归档(`archive/2026-09/plans-done/`)。

## 0. 目标(来自产品诉求)

1. 滤镜处理沉入 **OpenGL/GPU 着色器**(blur / mosaic / Kuwahara 均有 GLSL 版,且可扩展)。
2. 支持 **视频背景**(设置里已有 `bg_type: image|video` 与视频文件过滤器,但全仓无 QMediaPlayer——
   这是文档与代码的断层,本次补齐)。
3. 支持 **Shadertoy 风格程序化着色器背景**:兼容 `iResolution / iTime / iChannel0..3` 约定的预设库,
   可导入外部 `.glsl`。
4. **CPU 管线保留为默认与回退**:无 GL 环境、静态图场景下不降级体验;GPU 只承担 CPU 做不好的负载。

## 1. 现状与证据(2026-08-27 实测)

| 项 | 现状 | 证据 |
|---|---|---|
| 效果实现 | `bg_effects.py`:blur(QGraphicsBlurEffect+镜像补边)、mosaic、kuwahara(numpy 积分图+纯 Python 回退) | commit `1e8bdb3`;单测 12 项 |
| blur 耗时 | ~24ms@FHD(离线),含下采样 | 实测 |
| kuwahara 耗时 | numpy ~0.3-0.9s@1024 上限;回退 ~0.7s@200px | 实测 |
| 调用时机 | **paintEvent 内同步解码+特效**(首帧/换图/换特效/换强度) | `window.py` paintEvent |
| 交互 | 强度滑块每 tick 存盘+全量重特效+全 UI 重样式 → 已加 150ms 防抖 | commit `1e8bdb3` |
| blur 图像偏移 | 根因=环绕平铺补边;镜像补边修复,质量质心漂移 2.2-3.8px → ≤0.3px | commit `1e8bdb3` |
| 设置校验 | `bg_effect` 白名单缺失 kuwahara → 已放行 | commit `42b4624` |
| 视频 | `bg_type()` 文档声明 image|video,实际无渲染实现 | 证据缺失 |
| GL 能力 | PySide6 6.11;app.py 启动预热 GL 上下文;image_viewer 有 QOpenGLWidget+无 GL 回退 | 代码 |
| QtMultimedia | QMediaPlayer/QVideoSink 可导入 | 实测 |

瓶颈本质:**不是算力,是"同步重算"的调用架构**。GPU 化并不能替代异步化;两件事都要做,顺序:先异步(已部分完成),再 GPU(本文)。

## 2. 设计原则

1. **分层渲染,择优后端**。`BackgroundManager` 按 背景类型 + 效果类型 + GL 可用性 选择:
   - 静态图像 + CPU 可胜任 → **CPU 后端**(现状管线,缓存 QPixmap);
   - 静态图像 + 高成本效果(Kuwahara 强度大) → **GL 后端**离线 FBO 渲染一次,结果缓存为纹理/位图;
   - 视频 / 程序化着色器 / iTime 动画 → **GL 后端实时**;
   - 无 GL → 一律回退 CPU(视频降级为首帧图或禁用)。
2. **每次提交可验证**(证据文化):效果正确性用 offscreen 数值断言;GL 路径用 FBO 冒烟测试
   (GL 上下文可用时);性能有预算表。
3. **不引入第三方渲染库**:全部用 Qt(OpenGL API + QtMultimedia),保持零新增运行时依赖
   (numpy 保持可选快路径,已有回退)。
4. **设置与渲染解耦**:设置层只表达"要什么"(type/effect/intensity/shader 预设),
   渲染层决定"怎么画"。`themes` 保持现有读取 API,新增键走同一校验器。

## 3. 分层架构

```
AssetsManager/background/                  # 新包
├── manager.py        BackgroundManager    # 策略选择:backend = f(gl_ok, bg_type, effect)
├── sources.py        FrameProducer 抽象
│                       ImageSource  (静态图 -> QImage/纹理)
│                       VideoSource  (QMediaPlayer+QVideoSink -> QVideoFrame -> 纹理/QImage)
│                       ShaderSource (程序化:仅 GLSL,无输入图像)
├── pipeline.py       EffectChain + EffectSpec{kind, intensity, params}
│                       → cpu: bg_effects 现有函数
│                       → gl : GLSL pass 列表(每种效果一个 fragment)
├── gl/
│   ├── surface.py    BackgroundSurface(QOpenGLWidget)  # GPU 画布(见 §5 集成)
│   ├── renderer.py   FBO ping-pong 渲染器:全屏 quad + pass 链 + 缓存
│   ├── shaders/      blur.frag / mosaic.frag / kuwahara.frag / shadertoy_base.frag
│   └── presets.py    Shadertoy 预设注册表 {name: fragment}
└── settings_bridge.py  把 settings -> BackgroundManager 配置(单向)
```

**EffectChain 语义**(CPU/GL 统一):`[ {kind: "blur", intensity: 12}, … ]`。
未来支持多段链(如 blur→kuwahara),本期单段即可,接口按链设计。

**数据流(静态图 + GL)**:
`ImageSource.decode` → 上传纹理 → 逐 pass FBO 渲染(镜像采样) → 结果纹理/位图缓存 →
按窗口尺寸缩放绘制。**只渲染一次并缓存**,窗口 resize 仅重缩放(现状协议)。

**数据流(视频/着色器,实时)**:每帧 `newFrame` → 纹理更新 → pass 链 → 绘制;`iTime` 由
QElapsedTimer 推进;窗口隐藏/最小化时暂停(省电)。

## 4. GLSL 效果集(与 CPU 版逐条对应)

| 效果 | GLSL 方案 | 与 CPU 的一致性 |
|---|---|---|
| blur | 两趟可分离高斯(水平/垂直),坐标镜像采样(mirror 模式或手动 `mirror(uv)`) | 镜像补边语义=CPU 修复后语义;半径=intensity |
| mosaic | 最近邻块采样:`floor(uv * block)/block` | 与缩放近似一致(块相位允许差异) |
| kuwahara | 每像素 4 象限窗口 IO 查询,min 方差,输出均值 | 与 numpy 版算法一一对应(半径=窗半宽,窗边长 r+1) |
| shadertoy | `shadertoy_base.frag` 模板:统一 uniform `iTime/iResolution/iChannel0..3/iMouse`;预设仅替换 mainImage | 兼容绝大多数 Shadertoy 输入场景;iChannel 由 ImageSource/VideoSource 提供纹理 |

uniform 归一:预制 `uniforms.py` 映射(`{iTime: float, iResolution: vec3, ...}`),着色器编译失败一律
日志+回退到 CPU 效果,绝不黑屏。

## 5. 窗口集成(关键技术难点)

**约束**:QOpenGLWidget 是原生(HWND)子窗口,恒在所有非原生兄弟之上 → 不能简单"垫底",
否则会盖住 dock/面板。

**本期方案(hybrid)——精确挂载点(2026-08-27 前端层实测)**:
- 窗口装配事实:`MainWindow._setup_ui` 中 `self.file_list = self._create_file_list_panel()`、
  `self.setCentralWidget(self.file_list)`(`window.py` L461-462);sidebar/info 为左右 dock
  (`window.py` L465-477);面板经 `WA_StyledBackground` + 主题半透明色透出壁纸
  (`panels/base.py` L29、`themes.panel_color()` 带 bg_panel_opacity)。
- 因此 **GPU 画布的挂载点 = 把 `setCentralWidget(self.file_list)` 换成
  `setCentralWidget(gl_host)`**:`BackgroundSurface(QOpenGLWidget)` 作中央区域宿主,
  `file_list` re-parent 进其布局并保持透明样式;sidebar/info dock 区继续走 CPU
  paintEvent 壁纸。QOpenGLWidget 支持子控件在其 GL 内容之上合成(Qt 文档化能力),
  该项列为 M2 首步尖峰验证(风险 R-1)。
- 双区同源同链:CPU 与 GL 使用同一 base 图与效果链,且 framing 数学必须一致
  (`KeepAspectRatioByExpanding` + 居中裁剪,对齐 `window.py` L264 语义),保证区域间
  视觉连续(风险 R-2)。

**长期方案(全窗 GPU,若产品需要)**:
- 把 dock/面板收进一个全窗透明容器(如 `QWidget` 覆盖层 + `WA_TranslucentBackground` 的画布 child),
  画布层提升为唯一底层 → 需重构窗口装配,单独立项评估(Sprint 之后)。

**HiDPI**:viewport 尺寸乘 `devicePixelRatio`;纹理以物理像素上传;CPU 回退保持现状 dpr 语义。

**节能**:动画着色器只在窗口可见且未最小化时推进 iTime / 解码视频;`aboutToCompose` 循环由
`frameSwapped` 驱动,空闲无差异不重绘。

## 6. 设置与 UX(增量,兼容现状)

- 背景类型沿用 `bg_type`: `image`(现状)/ `video`(新,真正生效)/ `shader`(新)。
- 效果菜单沿用 `bg_effect`: `none/blur/mosaic/kuwahara/shader`;类型=shader 时,效果固定为
  `shader`,另出 **着色器预设下拉**(`shaders/presets.py`)与 "导入 .glsl…" 按钮。
- 强度滑块语义:blur=半径px、mosaic=块px、kuwahara=窗半宽px、shader=强度 uniform(预设自定义,
  默认映射为 float 0..1)。
- 校验器白名单扩充:`bg_type ∈ {image, video, shader}`、`bg_effect ∈ {…, shader}`、
  新键 `bg_shader_preset`(str,存在性由 presets 表校验)。
- 滑块防抖沿用 150ms;效果/类型切换后的重算一律走后端异步管线,不阻塞 paintEvent。

## 7. 性能预算与验证口径

| 场景 | 预算 | 验证 |
|---|---|---|
| 静态图 CPU 路径 | 首应用 ≤300ms,之后 0(缓存) | 现 tests + 计时探针 |
| 静态图 GL 路径 | 首渲染 ≤100ms@1080p,缓存后 0 | FBO 冒烟 + QElapsedTimer |
| 视频背景 | 1080p30 稳定,CPU 占用 <10%(单核) | 帧间隔统计 |
| 动画着色器 | ≥30fps@1080p | 帧间隔统计;窗口隐藏自动暂停 |
| 无 GL | 功能不缺失(回退 CPU/禁用视频) | 强制 software GL 跑测试 |

测试策略:
- 效果单元测试(offscreen):CPU/GL 输出在"边缘保持、均匀区、尺寸"断言上对齐;
- `QOpenGLShaderProgram.link()` 全预设编译校验(offscreen + GL 可用时);
- FBO 冒烟:渲染 1px 已知色 → 读回断言(GLM 不可用时 skip);
- settings 校验器回归(延续 `42b4624` 的范式)。

## 8. 里程碑与依赖

| M | 内容 | 产出 | 依赖 |
|---|---|---|---|
| M1 ✅ | CPU Kuwahara + blur 漂移修复 + 滑块防抖 + 校验器放行 | commits `1e8bdb3` `42b4624` | 无 |
| M2 | `background/` 包 + Surface + GLSL blur/mosaic/kuwahara + hybrid 集成(central 层) | GL 冒烟测试绿 | M1 |
| M3 | VideoSource(QMediaPlayer/QVideoSink 纹理上传)+ `bg_type=video` 生效 | 视频好依赖证据(帧率/CPU) | M2 |
| M4 | Shadertoy 预设库 + .glsl 导入 + iTime 动画 + 节能暂停 | 预设≥3 条 + 导入用例 | M2 |

每里程碑:文档 gate(`check_documents`/`check_doc_stats`)与 ruff 全绿;提交严格限定本里程碑文件
(外部任务在途文件一律不触碰)。

## 9. 决策记录

| # | 决策 | 理由 |
|---|---|---|
| D-1 | CPU 静态为默认、GL 按需启用 | readback 静态图反而慢;回退保障无 GL 机器 |
| D-2 | GL 画布本期只做 central 区,不做全窗底层 | 原生子窗口堆叠约束;hybrid 风险最低 |
| D-3 | 着色器失败即回退 CPU,绝不黑屏 | 稳健第一 |
| D-4 | 零第三方渲染依赖(numpy 保持可选) | 打包/维护成本 |
| D-5 | 设置只表达意图,渲染层决定后端 | 未来后端可替换而不改设置协议 |

## 10. 前端层集成验证(2026-08-27 实测,与设置-桌面层逐项核对)

本节把 §3-§8 的设计断言对照真实前端层代码验证;违反/未覆盖处即为本设计的修正点。

### 10.1 窗口装配与 GPU 挂载点(已验证,§5 已修订)

| 断言 | 实测 | 结论 |
|---|---|---|
| central 区=工作区 | `setCentralWidget(self.file_list)`(`window.py` L462);sidebar/info 为左右 dock(L465-477) | **挂载点确定为 `setCentralWidget` 替换为 GL host**,file_list re-parent;dock 区保留 CPU 壁纸 |
| 面板透明机制 | `WA_StyledBackground` + 主题半透明色(`panels/base.py` L29;`themes.panel_color()` 用 bg_panel_opacity) | file_list re-parent 后沿用样式即可透出 GL 内容,无需改面板 |
| 多窗口刷新 | `WindowCoordinator` 统一转发 `refresh_bg`(`window_coordinator.py` L132) | 每个窗口独立的 BackgroundManager/Surface 挂同一通知即可 |

### 10.2 设置面验证(settings_dialog Appearance 标签)

现状控件(实测 L126-216):bg_enabled 复选框、bg_image 路径 + 浏览(文件过滤器**已含 mp4/webm/avi**)、
panel/header 透明度 ×2、效果菜单 + 强度滑块(已防抖)、clear。保存点 `_on_bg_setting_changed`
(L482-487)共六键。通知链:`_BackgroundStyleHost._on_bg_style_changed`(L36-37)协议 →
`MainWindow._on_bg_style_changed` → `refresh_bg()`(window.py L325)。

**验证发现的两处设计缺口(已纳入修订)**:
- **G-1:`bg_type` 无任何 set 点、无选择 UI**(全仓仅 `themes.bg_type()` 读取)。浏览过滤器可选视频,
  但选了 mp4 后 `QPixmap(mp4)` 解码为 null → 背景静默消失。→ M3 必须增设"背景类型"菜单行
  (image/video/shader),写入 `bg_type`。
- **G-2:通知链只覆盖 CPU 刷新**。GL host 需在 `_on_bg_style_changed` 同一处理函数里触发
  `BackgroundManager.refresh()`(重建管线/重传纹理/重渲染一次,异步排队,不进 paintEvent)。

### 10.3 设置协议扩展(键/校验器/i18n,全部走现有机制)

- 新键:`bg_type`(image|video|shader)、`bg_shader_preset`(非空 str,存在性由 presets 表校验,
  未知预设回退首个)。
- 校验器 `_VALIDATORS`(settings.py L31-46)追加:
  `"bg_type": lambda v: v in ("image", "video", "shader")`、
  `"bg_shader_preset": lambda v: isinstance(v, str) and bool(v)`。
- i18n 增量(继 840 键之后 ×3 文件):`settings.bg_type`、`settings.bg_type_image`、
  `settings.bg_type_video`、`settings.bg_type_shader`、`settings.bg_shader_preset`、
  `settings.bg_shader_import`。UI 位置:bg_enabled 与 bg_image 行之间放类型菜单行;
  类型=shader 时显示预设下拉 + 导入按钮。
- 强度滑块语义沿用 §6;类型=video/shader 时效果链默认 none(视频/程序化内容自带动态),
  可叠加 GLSL 版效果(M2 交付后可点亮)。

### 10.4 打包与运行时注记

- `AssetManager.spec` 存在;M3 视频需在 spec 收集 QtMultimedia 插件
  (`collect_qt_plugins("multimedia")` 或同义 collect 条目),否则 frozen 版无
  QMediaPlayer 后端。
- 无 GL 环境:GL 后端探测失败 → BackgroundManager 全量回退 CPU;video 取首帧 QImage 走
  静态 CPU 渲染(与现有无声失效相反——改进)。

### 10.5 风险登记(修订后)

| # | 风险 | 缓解 |
|---|---|---|
| R-1 | QOpenGLWidget 承载 file_list 子控件合成,实际窗体系表现需尖峰验证 | M2 第一步做 10 分钟尖峰:GL host + reparent 冒烟(含高 DPI) |
| R-2 | CPU/GL 双区各自渲染,尺寸/裁剪不一致会产生区域接缝 | 同一 framing 数学常量共享;双区同源同链 |
| R-3 | 动画着色器/视频能耗 | 窗口不可见/最小化即暂停(MainWindow `isVisible` 事件,WindowCoordinator 已有窗口清单) |
| R-4 | 着色器编译失败黑屏 | D-3:失败即回退 CPU,日志告警 |
| R-5 | frozen 版缺 QtMultimedia 插件 | §10.4 spec 注记 |

### 10.6 里程碑修正

- M2 首位新增:**GL host 尖峰验证(R-1)** → 通过后才进入 GLSL 三效果与 hybrid 集成;
- M3 拆分:a) 背景类型 UI + `bg_type` 设置链路(G-1);b) VideoSource 渲染 + spec 打包;
- M4 不变(Shadertoy 预设库 + .glsl 导入 + iTime 动画 + 节能)。