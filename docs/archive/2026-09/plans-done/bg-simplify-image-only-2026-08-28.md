# 背景方案精简:仅图片背景 + 着色器化滤镜特效(2026-08-28)
> 状态：**现行** · 状态登记：2026-09-02（文档整理轮补登）


## 决策

背景**源**收敛为一张静态图片;移除视频背景与"着色器作为背景类型"。

滤镜**特效层**保持并着色器化:`none / blur / mosaic / kuwahara / shader` 五种效果,
由 GPU(GLSL 管线)渲染,GL 不可用时 CPU 回退(`shader` 无 GL 时降级为原图,绝不黑屏)。

## 为什么

1. 视频背景与程序化着色器背景需要常驻 `QOpenGLWidget` 底层,而 Qt 原生子窗口
   堆叠约束使"全窗口 GPU 背景"必须重构窗口装配(把 dock/面板全部 re-parent
   进 GL 宿主),风险和收益不成比例。用户明确放弃视频背景。
2. "高级着色器滤镜"的价值卡在**效果层**,而非背景源:把图片当作 `iChannel0`
   输入、用 Shadertoy 风格的 `mainImage` 片段做滤镜,即可在静态图片背景下
   实现任意高级着色器效果,且结果仍走普通的 `MainWindow.paintEvent` 全窗口
   绘制——无原生窗口堆叠问题、天然全窗口覆盖。

## 架构

```
设置意图                  滤镜渲染                         全窗口合成
bg_effect (intensity)  →  ImageEffectRenderer  →  QImage →  paintEvent CPU 绘制
bg_shader_preset            ├─ GPU: 离屏 QOpenGLContext
                            │        + FBO + GlPipeline(GLLL 1.20)
                            └─ CPU: bg_effects (blur/mosaic/kuwahara)
```

- `AssetsManager/background/pipeline.py` — `ImageEffectRenderer.render(image, effect, intensity, preset)`
  - blur/mosaic/kuwahara: 先 GL(`render_still`, ping-pong FBO 链),失败回 CPU;
  - shader: `GlPipeline.render_shader_preset`(离屏 Shadertoy 片段,iChannel0=图片);
  - none: 原图。
- 删除: `gl/surface.py`(QOpenGLWidget 背景宿主)、`sources.py`(视频/程序化源)、
  `manager.py`(背景源决策表)。`model.py` 只保留 `EffectSpec`/`EffectChain`。
- 设置协议: 保留 `bg_effect`(含 `shader`)、`bg_effect_intensity`、`bg_shader_preset`;
  删除 `bg_type`。i18n 净增 `settings.bg_effect_shader`(Shader 效果标签)。

## 已删除(视频背景相关)

- 窗口级 `VideoSource` 视频喂帧、30fps 滚动节流、`eventFilter` 滚轮监听;
- `BackgroundManager` 决策表、`BackgroundSurface` GL 中央宿主挂载/卸载、
  `BackendPlan`、`SourceKind`/`BackendName`;
- 背景类型菜单行(image/video/shader)及其 4 个 i18n 键。

## 验证口径

- 单元回归 `tests/core/test_background_renderer.py`(offscreen:CPU 回退 + shader 降级);
- 设置校验 `bg_effect` 放行 `shader`、`bg_shader_preset` 非空串;
- 删除 `test_background_pipeline.py`、`test_background_gl_smoke.py`
  (其覆盖的 GL 构件已随源重构移除)。