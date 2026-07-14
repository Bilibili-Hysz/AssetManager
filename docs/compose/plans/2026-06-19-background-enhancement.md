# Background Enhancement Implementation Plan

> **Goal:** Add video backgrounds (MP4 via QMediaPlayer) and image effects (blur, mosaic) to the background system.

**Architecture:** Extend current `paintEvent` rendering with video frame support and image effect processing. Settings UI gets type dropdown and effects section.

---

### Task 1: Extend themes.py settings getters

**Covers:** [S3]

**Files:**
- Modify: `AssetsManager/core/themes.py`
- Test: `tests/core/test_themes.py`

**Steps:**
- [ ] Add `bg_type() -> str` (returns "image" or "video")
- [ ] Add `bg_blur_enabled() -> bool`
- [ ] Add `bg_blur_intensity() -> int`
- [ ] Add `bg_mosaic_enabled() -> bool`
- [ ] Add `bg_mosaic_intensity() -> int`
- [ ] Add tests for each getter

---

### Task 2: Add image effect processing functions

**Covers:** [S3]

**Files:**
- Create: `AssetsManager/core/bg_effects.py`
- Test: `tests/core/test_bg_effects.py`

**Steps:**
- [ ] Implement `apply_blur(pixmap, radius) -> QPixmap` — box blur via QImage pixel manipulation
- [ ] Implement `apply_mosaic(pixmap, block_size) -> QPixmap` — pixelation via scale down + nearest-neighbor up
- [ ] Write tests with sample images

---

### Task 3: Add QMediaPlayer video background to MainWindow

**Covers:** [S2]

**Files:**
- Modify: `AssetsManager/window.py`

**Steps:**
- [ ] Add `_video_player` (QMediaPlayer) and `_video_sink` (QVideoSink) setup
- [ ] Modify `paintEvent` to render video frames when bg_type == "video"
- [ ] Add `_start_video_bg(path)` and `_stop_video_bg()` methods
- [ ] Video: auto-loop, muted, paused when window minimized
- [ ] Add video format detection from file extension (.mp4, .webm, .avi)

---

### Task 4: Integrate effects into paintEvent

**Covers:** [S2]

**Files:**
- Modify: `AssetsManager/window.py`

**Steps:**
- [ ] In `paintEvent`, after loading raw pixmap, apply blur/mosaic if enabled
- [ ] Cache the processed (blurred/mosaicked) pixmap separately from raw
- [ ] Invalidate processed cache when effect settings change

---

### Task 5: Update settings dialog UI

**Covers:** [S2]

**Files:**
- Modify: `AssetsManager/dialogs/settings_dialog.py`

**Steps:**
- [ ] Add type dropdown (Image/Video) after file path
- [ ] Add "Image Effects" group box with blur toggle + slider, mosaic toggle + slider
- [ ] Wire type change to enable/disable effects section
- [ ] Wire blur/mosaic settings to AppSettings
- [ ] Add browse filter for video formats (.mp4, .webm, .avi)

---

### Task 6: Wire settings to live preview

**Covers:** [S4]

**Files:**
- Modify: `AssetsManager/dialogs/settings_dialog.py`
- Modify: `AssetsManager/window.py`

**Steps:**
- [ ] Blur/mosaic setting changes trigger `refresh_bg()`
- [ ] Type change triggers video/image mode switch
- [ ] Settings persist to AppSettings on change

---

### Task 7: Run quality gate

Run: `python -m ruff check . && python -m pyright && python -m pytest -q`
Expected: All pass.
