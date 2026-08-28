# Background Enhancement: Video + Effects Spec
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

## [S1] Problem
Current background system only supports static images with opacity control. No video backgrounds, no blur, no mosaic effects.

## [S2] Solution
Add MP4 video backgrounds via QMediaPlayer, and blur/mosaic effects for images.

### Settings UI
- Enable checkbox (shared for image/video)
- File path + browse button (supports images and videos)
- Type dropdown: Image / Video (auto-detected from file extension)
- Overall opacity slider
- Panel opacity slider
- Image effects section:
  - Blur: on/off + intensity slider (0-100)
  - Mosaic: on/off + intensity slider (0-100)
- Image effects grayed out when type is Video

### Video background
- Use QMediaPlayer + QVideoSink to render frames as QPixmaps
- Auto-loop, muted
- Render in paintEvent (same pattern as current image bg)
- Graceful fallback to image mode if QMediaPlayer unavailable

### Blur effect
- Apply blur to the raw QPixmap before scaling
- Use QImage pixel manipulation (box blur or Gaussian approximation)
- Intensity controls blur radius (1-50 pixels)

### Mosaic effect
- Scale image down by factor, then scale back up (nearest-neighbor)
- Intensity controls block size (2-50 pixels)

### Settings storage
- `bg_type`: "image" or "video"
- `bg_blur_enabled`: bool
- `bg_blur_intensity`: int (1-50)
- `bg_mosaic_enabled`: bool
- `bg_mosaic_intensity`: int (2-50)

## [S3] Implementation files
- `AssetsManager/core/themes.py` — add bg_type(), bg_blur_enabled(), etc.
- `AssetsManager/window.py` — modify paintEvent for video/effects
- `AssetsManager/dialogs/settings_dialog.py` — add image effects UI
- `tests/core/test_themes.py` — tests for new settings getters
- `tests/unit/test_bg_effects.py` — tests for blur/mosaic logic

## [S4] Acceptance criteria
- Video backgrounds play automatically, looped, muted
- Blur effect works on images with adjustable intensity
- Mosaic effect works on images with adjustable intensity
- Effects only available for images (grayed out for video)
- Settings persist and reload correctly
- No performance regression for static image backgrounds
