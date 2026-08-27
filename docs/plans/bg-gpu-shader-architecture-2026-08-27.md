# 背景渲染新架构:GPU 着色器 / 视频 / Shadertoy 程序化背景(2026-08-27,设计稿)

> **updated**: 2026-08-27
> **状态**:设计定稿待实施;M1(CPU 默认路径)已于 2026-08-27 完成并提交。
> **范围**:`docs/full-review/**` 不涉及。本文是 LIVING 与证据文化下的实施蓝图,每步落地必须伴随
> commit + 命令 + 平台 + 版本 + digest 的 dated 证据。

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

**本期方案(hybrid)**:
- `BackgroundSurface(QOpenGLWidget)` 作为 **central widget 区域的背景层**(文件列表/信息面板所在
  的中央工作区),dock 侧/顶面板仍然走现有 CPU 壁纸(paintEvent + 透明样式)。
- 两层渲染同源(base 图像 + 同一效果链),面板区域在视觉上与中央 GPU 区域连续。
- 意义:不动 QMainWindow/dock 结构,把 GPU 用在"用户注视的中央内容面",风险最低。

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