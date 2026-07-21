# Qt Viewer HQ Zoom Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the current Qt image viewer's interactive zoom/pan speed while raising settled (idle) image quality close to the Tk/LANCZOS path, without adding a user mode switch in v1.

**Architecture:** Keep matrix-based interactive zoom on a full-resolution source image. Fix pixmap-item smoothing so bilinear filtering actually applies during interaction. After zoom/fit settles (~140ms idle), asynchronously resample the source to the current on-screen pixel size with Pillow LANCZOS, swap the displayed pixmap, and compensate the view transform so the image does not jump. Cancel stale HQ jobs with a token when the user zooms again or switches images.

**Tech Stack:** Python, PySide6 (`QGraphicsView` / `QGraphicsPixmapItem` / `QThread`), Pillow (`Image.Resampling.LANCZOS`), `unittest` with `QT_QPA_PLATFORM=offscreen`.

---

## Scope Check

Single subsystem: `ImageViewer` quality pipeline in `qt_image_viewer.py`, plus focused tests in `tests/test_qt_workbench.py`. No workbench UX toggle, no config flag, no Tk changes in v1. Optional Fast/Quality switch is explicitly out of scope unless post-merge manual testing shows settle jank on target machines.

## Background (why this plan exists)

| Path | Mechanism | Feel |
|------|-----------|------|
| Tk `image_classifier.render_image` | Every zoom resizes pixels; idle uses **LANCZOS** | Slow, high precision |
| Qt `ImageViewer.zoom_by` today | View `scale()` only; item default **FastTransformation** | Fast, hard/aliased |

Root quality bugs / limits today:

1. `setRenderHint(SmoothPixmapTransform)` on the view does **not** reliably smooth `QGraphicsPixmapItem` (item defaults to `Qt.FastTransformation` and overrides painter hints).
2. Idle path only toggles a render hint; it never resamples pixels.
3. `_sharp_zoom_ratio = 1.2` intentionally disables smoothing above slight zoom-in, which fights the classification use case.

## Design Decisions (locked)

1. **Default only (Balanced):** interactive matrix zoom + idle HQ settle. No toolbar mode in v1.
2. **Always prefer smooth filtering for interactive display** after P0; drop “sharp above 1.2× fit” policy.
3. **HQ algorithm:** Pillow `LANCZOS` (already in `requirements.txt`, matches Tk settle quality).
4. **HQ timing:** reuse single-shot timer (~140ms) after zoom; also schedule after `fit_to_window` / initial load fit.
5. **No visual jump:** when swapping source↔HQ pixmap, compensate transform so effective on-screen scale and center stay the same.
6. **Safety clamps:** cap HQ output longest edge at `8192` px; skip HQ when target size ≈ current display size (≤1% scale delta) or target is empty.
7. **Thread safety:** resample off UI thread; apply only if job token still current.
8. **Out of scope v1:** user-facing quality mode switch, config persistence, changing wheel zoom factor (`1.25`), changing pan behavior.

## File Structure

- Modify `qt_image_viewer.py`: source-image retention, smooth item mode, HQ worker, settle/apply/cancel pipeline, transform compensation helpers.
- Modify `tests/test_qt_workbench.py`: replace obsolete sharp-at-high-zoom test; add smooth-mode, HQ-settle, cancel-on-rezoom, no-jump, and fit-settle tests.
- No `qt_workbench.py` / `config.json` / docs user-facing changes required for v1 (behavior is default improvement).

## State Model (implement against this)

Add these fields on `ImageViewer`:

```python
self._source_image: QImage | None = None   # full-res original
self._display_scale: float = 1.0           # displayed_pixmap_width / source_width
self._hq_token: int = 0                    # cancel stale HQ jobs
self._hq_threads: dict = {}                # token -> (thread, worker) like load threads
self._max_hq_edge: int = 8192
self._hq_scale_epsilon: float = 0.01
# keep existing: _fit_scale, _zoom_quality_timer, _load_token, etc.
```

Definitions:

- `view_scale = transform().m11()`
- `effective_scale = view_scale * _display_scale`  
  (how many screen pixels one source pixel occupies)
- When showing the raw source pixmap: `_display_scale == 1.0`
- When showing an HQ pixmap of width `W_hq` from source width `W_src`: `_display_scale == W_hq / W_src`, and typically `view_scale ≈ 1.0` after apply (or any pair that preserves `effective_scale`)

## Transform Compensation (must not jump)

When replacing the item pixmap with a differently sized image of the same content:

```python
def _swap_pixmap_preserving_view(self, pixmap: QPixmap, new_display_scale: float) -> None:
    if pixmap.isNull() or not self._has_image:
        return

    old_display_scale = max(self._display_scale, 1e-6)
    old_view_scale = max(self.transform().m11(), 1e-6)
    effective = old_view_scale * old_display_scale

    # Preserve the scene point currently under the viewport center.
    anchor_view = self.viewport().rect().center()
    anchor_scene = self.mapToScene(anchor_view)

    self._pixmap_item.setPixmap(pixmap)
    self._pixmap_item.setOffset(0, 0)
    self.setSceneRect(QRectF(pixmap.rect()))
    self._display_scale = max(new_display_scale, 1e-6)

    new_view_scale = effective / self._display_scale
    self.resetTransform()
    self.scale(new_view_scale, new_view_scale)

    # Re-center so the same scene content stays under the viewport center.
    new_anchor_view = self.mapFromScene(anchor_scene)
    delta = anchor_view - new_anchor_view
    self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + delta.x())
    self.verticalScrollBar().setValue(self.verticalScrollBar().value() + delta.y())
```

Interactive zoom must operate on the **source** pixmap so quality work does not compound and so zoom math stays simple:

```python
def _ensure_source_display(self) -> None:
    if self._source_image is None or self._source_image.isNull():
        return
    if abs(self._display_scale - 1.0) < 1e-6:
        return
    source_pixmap = QPixmap.fromImage(self._source_image)
    self._swap_pixmap_preserving_view(source_pixmap, 1.0)
```

## HQ Target Size

```python
def _target_hq_size(self) -> tuple[int, int] | None:
    if self._source_image is None or self._source_image.isNull():
        return None
    src_w = self._source_image.width()
    src_h = self._source_image.height()
    if src_w <= 0 or src_h <= 0:
        return None

    effective = max(self.transform().m11(), 1e-6) * max(self._display_scale, 1e-6)
    target_w = max(1, int(round(src_w * effective)))
    target_h = max(1, int(round(src_h * effective)))

    longest = max(target_w, target_h)
    if longest > self._max_hq_edge:
        clamp = self._max_hq_edge / float(longest)
        target_w = max(1, int(round(target_w * clamp)))
        target_h = max(1, int(round(target_h * clamp)))

    # Skip if already displaying essentially this resolution.
    current_w = self._pixmap_item.pixmap().width()
    if current_w > 0:
        ratio = target_w / float(current_w)
        if abs(ratio - 1.0) <= self._hq_scale_epsilon:
            return None

    return target_w, target_h
```

## Pillow Conversion Helpers (module-level or static)

```python
from io import BytesIO
from PIL import Image

def _qimage_to_pil(image: QImage) -> Image.Image:
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.ReadWrite)
    # PNG round-trip is simple and lossless for typical classifier inputs.
    image.save(buffer, "PNG")
    return Image.open(BytesIO(buffer.data().data())).convert("RGBA")

def _pil_to_qimage(pil_image: Image.Image) -> QImage:
    bio = BytesIO()
    pil_image.save(bio, format="PNG")
    out = QImage()
    out.loadFromData(bio.getvalue())
    return out.copy()

def _lanczos_resize(source: QImage, width: int, height: int) -> QImage:
    pil = _qimage_to_pil(source)
    resized = pil.resize((width, height), Image.Resampling.LANCZOS)
    return _pil_to_qimage(resized)
```

Notes for implementer:

- Prefer `QImage.Format.Format_RGBA8888` conversion if PNG round-trip proves too slow in manual tests; the plan accepts PNG first for correctness, then optimize only if settle feels laggy.
- Worker must copy the source `QImage` before leaving the UI thread (`source.copy()`).

---

### Task 1: Fix Interactive Smoothing (P0)

**Files:**
- Modify: `qt_image_viewer.py`
- Modify: `tests/test_qt_workbench.py` (replace obsolete sharp-zoom assertion)

- [ ] **Step 1: Rewrite the obsolete quality test to the new policy**

Replace `test_viewer_uses_sharp_rendering_at_high_zoom_and_smooth_fit` in `tests/test_qt_workbench.py` with:

```python
    def test_viewer_keeps_smooth_pixmap_item_at_high_zoom_and_fit(self):
        viewer = ImageViewer()
        viewer.resize(800, 600)
        viewer.show()
        self.app.processEvents()
        image = QImage(240, 160, QImage.Format.Format_RGB32)
        image.fill(QColor("#4f7fc8"))

        viewer._handle_image_loaded(Path("sample.jpg"), viewer._load_token, image, "")
        self.app.processEvents()

        self.assertEqual(
            viewer._pixmap_item.transformationMode(),
            Qt.TransformationMode.SmoothTransformation,
        )
        self.assertTrue(
            bool(viewer.renderHints() & QPainter.RenderHint.SmoothPixmapTransform)
        )

        viewer.zoom_by(2.0)
        viewer._finish_zoom_interaction()
        self.assertEqual(
            viewer._pixmap_item.transformationMode(),
            Qt.TransformationMode.SmoothTransformation,
        )
        self.assertTrue(
            bool(viewer.renderHints() & QPainter.RenderHint.SmoothPixmapTransform)
        )

        viewer.fit_to_window()
        self.assertEqual(
            viewer._pixmap_item.transformationMode(),
            Qt.TransformationMode.SmoothTransformation,
        )
        viewer.close()
        viewer.deleteLater()
        self.app.processEvents()
```

Add import if missing:

```python
from PySide6.QtCore import QPoint, QPointF, Qt
```

(`Qt` is already imported; no change needed if present.)

- [ ] **Step 2: Run the rewritten test — expect FAIL**

Run:

```bash
D:/miniforge3/envs/tool/python.exe -m unittest tests.FAKESECRET_i1j2k3l4m5n6o7p8q9r0 -v
```

Expected: FAIL because `_pixmap_item.transformationMode()` is still `FastTransformation` (default), and/or high-zoom path still clears smooth hints.

- [ ] **Step 3: Implement smooth item mode and drop sharp-above-1.2 policy**

In `qt_image_viewer.py`:

1. After creating `self._pixmap_item` in `__init__`, set:

```python
self._pixmap_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
```

2. Remove (or stop using) `self._sharp_zoom_ratio`.

3. Replace `_update_render_quality` with always-on smooth for both interactive and idle:

```python
def _update_render_quality(self, interactive: bool) -> None:
    # interactive reserved for future fast-path tweaks; v1 always smooths.
    del interactive
    self._pixmap_item.setTransformationMode(
        Qt.TransformationMode.SmoothTransformation
    )
    self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
```

4. Keep existing calls to `_update_render_quality(...)` so call sites stay stable.

5. Ensure `__init__` still enables `SmoothPixmapTransform` on the view (already true).

- [ ] **Step 4: Re-run the rewritten test — expect PASS**

```bash
D:/miniforge3/envs/tool/python.exe -m unittest tests.FAKESECRET_i1j2k3l4m5n6o7p8q9r0 -v
```

Expected: PASS

- [ ] **Step 5: Run existing viewer zoom tests — expect PASS**

```bash
D:/miniforge3/envs/tool/python.exe -m unittest \
  tests.FAKESECRET_q2r3s4t5u6v7w8x9y0z1 \
  tests.FAKESECRET_w1x2y3z4a5b6c7d8e9f0 \
  tests.FAKESECRET_a1b2c3d4e5f6g7h8i9j0 \
  -v
```

Expected: PASS (smoothing change must not break zoom math)

- [ ] **Step 6: Commit**

```bash
git add qt_image_viewer.py tests/test_qt_workbench.py
git commit -m "$(cat <<'EOF'
fix(viewer): apply smooth transform on pixmap item

Drop the high-zoom nearest-neighbor policy so classification
preview no longer looks hard-edged during matrix zoom.
EOF
)"
```

---

### Task 2: Retain Source Image and Display Scale Bookkeeping

**Files:**
- Modify: `qt_image_viewer.py`
- Modify: `tests/test_qt_workbench.py`

- [ ] **Step 1: Add failing tests for source retention**

Insert after the smooth-mode test:

```python
    def test_viewer_retains_source_image_and_unit_display_scale_on_load(self):
        viewer = ImageViewer()
        viewer.resize(800, 600)
        viewer.show()
        self.app.processEvents()
        image = QImage(320, 200, QImage.Format.Format_RGB32)
        image.fill(QColor("#214f6e"))

        viewer._handle_image_loaded(Path("sample.jpg"), viewer._load_token, image, "")
        self.app.processEvents()

        self.assertFalse(viewer._source_image.isNull())
        self.assertEqual(viewer._source_image.width(), 320)
        self.assertEqual(viewer._source_image.height(), 200)
        self.assertAlmostEqual(viewer._display_scale, 1.0, places=6)
        self.assertEqual(viewer._pixmap_item.pixmap().width(), 320)
        viewer.close()
        viewer.deleteLater()
        self.app.processEvents()

    def test_viewer_clear_resets_source_image_and_display_scale(self):
        viewer = ImageViewer()
        image = QImage(40, 30, QImage.Format.Format_RGB32)
        image.fill(QColor("#000000"))
        viewer._handle_image_loaded(Path("sample.jpg"), viewer._load_token, image, "")
        viewer.clear("empty")
        self.assertTrue(viewer._source_image is None or viewer._source_image.isNull())
        self.assertAlmostEqual(viewer._display_scale, 1.0, places=6)
        viewer.close()
        viewer.deleteLater()
        self.app.processEvents()
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
D:/miniforge3/envs/tool/python.exe -m unittest \
  tests.FAKESECRET_e2f3g4h5i6j7k8l9m0n1 \
  tests.FAKESECRET_k3l4m5n6o7p8q9r0s1t2 \
  -v
```

Expected: FAIL (`_source_image` / `_display_scale` missing)

- [ ] **Step 3: Implement bookkeeping in `ImageViewer`**

In `__init__`:

```python
self._source_image = None
self._display_scale = 1.0
self._hq_token = 0
self._hq_threads = {}
self._max_hq_edge = 8192
self._hq_scale_epsilon = 0.01
```

In `_handle_image_loaded` success path, before creating pixmap:

```python
self._source_image = image.copy()
self._display_scale = 1.0
self._hq_token += 1  # cancel any in-flight HQ from previous image
```

Then keep:

```python
pixmap = QPixmap.fromImage(self._source_image)
self._pixmap_item.setPixmap(pixmap)
...
```

In `clear` and failed load path:

```python
self._source_image = None
self._display_scale = 1.0
self._hq_token += 1
```

In `shutdown`, also bump `_hq_token` and quit any HQ threads (mirror load-thread shutdown; full HQ worker arrives in Task 3 — for now just initialize dict and token).

- [ ] **Step 4: Re-run Task 2 tests — expect PASS**

```bash
D:/miniforge3/envs/tool/python.exe -m unittest \
  tests.FAKESECRET_e2f3g4h5i6j7k8l9m0n1 \
  tests.FAKESECRET_k3l4m5n6o7p8q9r0s1t2 \
  -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add qt_image_viewer.py tests/test_qt_workbench.py
git commit -m "$(cat <<'EOF'
feat(viewer): retain full-resolution source image for HQ settle
EOF
)"
```

---

### Task 3: HQ Resample Worker + Idle Settle Apply

**Files:**
- Modify: `qt_image_viewer.py`
- Modify: `tests/test_qt_workbench.py`

- [ ] **Step 1: Add failing HQ settle tests**

```python
    def test_viewer_idle_settle_replaces_pixmap_with_hq_resize(self):
        viewer = ImageViewer()
        viewer.resize(400, 300)
        viewer.show()
        self.app.processEvents()
        # Large source so fit scale < 1 and HQ target differs from source size.
        image = QImage(2000, 1000, QImage.Format.Format_RGB32)
        image.fill(QColor("#8aa9c1"))
        viewer._handle_image_loaded(Path("big.jpg"), viewer._load_token, image, "")
        self.app.processEvents()

        source_w = viewer._source_image.width()
        pre_w = viewer._pixmap_item.pixmap().width()
        self.assertEqual(pre_w, source_w)

        # Force settle without waiting on real wall clock.
        viewer._zoom_quality_timer.stop()
        viewer._finish_zoom_interaction()

        # Allow worker completion.
        settled = self._process_events_until(
            lambda: viewer._pixmap_item.pixmap().width() != source_w
            and not viewer._hq_threads,
            timeout=3.0,
        )
        post_w = viewer._pixmap_item.pixmap().width()
        viewer.close()
        viewer.deleteLater()
        self.app.processEvents()

        self.assertTrue(settled)
        self.assertNotEqual(post_w, source_w)
        self.assertGreater(post_w, 0)

    def test_viewer_rezoom_cancels_stale_hq_and_restores_source_for_interaction(self):
        viewer = ImageViewer()
        viewer.resize(400, 300)
        viewer.show()
        self.app.processEvents()
        image = QImage(1800, 1200, QImage.Format.Format_RGB32)
        image.fill(QColor("#c18a8a"))
        viewer._handle_image_loaded(Path("big.jpg"), viewer._load_token, image, "")
        self.app.processEvents()

        viewer._finish_zoom_interaction()
        self._process_events_until(
            lambda: abs(viewer._display_scale - 1.0) > 1e-6 or not viewer._hq_threads,
            timeout=3.0,
        )

        # Next interactive zoom must return to source display scale for matrix zoom.
        before_token = viewer._hq_token
        viewer.zoom_by(1.25)
        self.assertEqual(viewer._pixmap_item.pixmap().width(), viewer._source_image.width())
        self.assertAlmostEqual(viewer._display_scale, 1.0, places=6)
        self.assertGreater(viewer._hq_token, before_token)

        viewer.close()
        viewer.deleteLater()
        self.app.processEvents()

    def test_viewer_hq_settle_preserves_effective_scale(self):
        viewer = ImageViewer()
        viewer.resize(500, 400)
        viewer.show()
        self.app.processEvents()
        image = QImage(1600, 900, QImage.Format.Format_RGB32)
        image.fill(QColor("#6e8f21"))
        viewer._handle_image_loaded(Path("big.jpg"), viewer._load_token, image, "")
        self.app.processEvents()

        viewer.zoom_by(1.5)
        effective_before = viewer.transform().m11() * viewer._display_scale

        viewer._finish_zoom_interaction()
        self._process_events_until(lambda: not viewer._hq_threads, timeout=3.0)
        # If HQ applied, display_scale may change; product must match.
        effective_after = viewer.transform().m11() * viewer._display_scale

        viewer.close()
        viewer.deleteLater()
        self.app.processEvents()

        self.assertAlmostEqual(effective_after, effective_before, places=3)
```

If `_process_events_until` is not available as an instance method on the test class, reuse the existing helper already used by `test_viewer_does_not_show_filename_loading_text_when_switching_images` (it is defined on `QtWorkbenchTest`).

- [ ] **Step 2: Run new tests — expect FAIL**

```bash
D:/miniforge3/envs/tool/python.exe -m unittest \
  tests.FAKESECRET_u3v4w5x6y7z8a9b0c1d2 \
  tests.FAKESECRET_s1t2u3v4w5x6y7z8a9b0 \
  tests.FAKESECRET_c2d3e4f5g6h7i8j9k0l1 \
  -v
```

Expected: FAIL (no HQ pipeline yet)

- [ ] **Step 3: Implement HQ worker class**

Add beside `_ImageLoadWorker` in `qt_image_viewer.py`:

```python
class _HqResizeWorker(QObject):
    finished = Signal(int, object, float, str)  # token, QImage, display_scale, error

    def __init__(self, token: int, source: QImage, width: int, height: int):
        super().__init__()
        self._token = token
        self._source = source
        self._width = width
        self._height = height

    @Slot()
    def run(self) -> None:
        try:
            resized = _lanczos_resize(self._source, self._width, self._height)
            if resized.isNull():
                self.finished.emit(self._token, QImage(), 1.0, "HQ resize failed")
                return
            display_scale = self._width / float(max(self._source.width(), 1))
            self.finished.emit(self._token, resized, display_scale, "")
        except Exception as exc:  # noqa: BLE001 - surface to UI path
            self.finished.emit(self._token, QImage(), 1.0, str(exc))
```

Add the Pillow helpers from the Design section near the top of the file (after imports). Required imports:

```python
from io import BytesIO
from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice  # QBuffer path; adjust if using QByteArray only
```

If `QBuffer` import path differs on the installed PySide6, use:

```python
from PySide6.QtCore import QByteArray, QBuffer
```

- [ ] **Step 4: Implement schedule / apply / cancel methods on `ImageViewer`**

```python
def _cancel_hq(self) -> None:
    self._hq_token += 1

def _schedule_hq_settle(self) -> None:
    self._zoom_quality_timer.start()

def _finish_zoom_interaction(self) -> None:
    self._update_render_quality(interactive=False)
    self._start_hq_resize()

def _start_hq_resize(self) -> None:
    if not self._has_image or self._source_image is None or self._source_image.isNull():
        return
    target = self._target_hq_size()
    if target is None:
        return
    target_w, target_h = target

    self._hq_token += 1
    token = self._hq_token
    source_copy = self._source_image.copy()

    thread = QThread(self)
    worker = _HqResizeWorker(token, source_copy, target_w, target_h)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(self._handle_hq_resized)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(lambda t=token: self._hq_threads.pop(t, None))
    self._hq_threads[token] = (thread, worker)
    thread.start()

@Slot(int, object, float, str)
def _handle_hq_resized(self, token: int, image: QImage, display_scale: float, error: str) -> None:
    if token != self._hq_token:
        return
    if error or image is None or image.isNull():
        return
    if not self._has_image:
        return
    pixmap = QPixmap.fromImage(image)
    self._swap_pixmap_preserving_view(pixmap, display_scale)
```

Implement `_target_hq_size` and `_swap_pixmap_preserving_view` exactly as in the Design section.

- [ ] **Step 5: Wire interactive zoom to source display + reschedule HQ**

Update `zoom_by`:

```python
def zoom_by(self, factor: float) -> None:
    if not self._has_image or factor <= 0:
        return

    self._cancel_hq()
    self._ensure_source_display()

    current_scale = max(self.transform().m11(), 0.01)
    fit_scale = max(self._fit_scale, 0.01)
    # fit_scale is measured when display_scale == 1.0 after fit_to_window.
    min_scale = max(fit_scale * self._min_zoom_ratio, 0.01)
    max_scale = max(fit_scale * self._max_zoom_ratio, min_scale)
    target_scale = min(max(current_scale * factor, min_scale), max_scale)
    relative_factor = target_scale / current_scale
    if abs(relative_factor - 1.0) < 0.0001:
        return

    self._fit_mode = False
    self._update_render_quality(interactive=True)
    self.scale(relative_factor, relative_factor)
    self._schedule_hq_settle()
```

Update `fit_to_window` so fit always uses source pixels, recomputes `_fit_scale` in source space, then schedules HQ:

```python
def fit_to_window(self) -> None:
    if not self._has_image:
        self._center_message()
        return

    self._cancel_hq()
    self._ensure_source_display()

    image_rect = self._pixmap_item.boundingRect()
    if image_rect.isNull():
        return

    self.setSceneRect(image_rect)
    self.resetTransform()
    self.fitInView(image_rect, Qt.AspectRatioMode.KeepAspectRatio)
    self._fit_mode = True
    self._fit_scale = max(self.transform().m11(), 0.01)
    self._display_scale = 1.0
    self._update_render_quality(interactive=False)
    self._schedule_hq_settle()
```

Update `_handle_image_loaded` success path end: after `fit_to_window()` (or preserve-view branch), ensure a settle is scheduled. If `fit_to_window` already schedules, no extra call needed. If preserve-view keeps transform, call `_schedule_hq_settle()` explicitly:

```python
if not self._preserve_view:
    self.fit_to_window()
else:
    self._update_render_quality(interactive=False)
    self._schedule_hq_settle()
```

Update `shutdown` to cancel HQ:

```python
def shutdown(self, timeout_ms: int = 1500) -> None:
    self._load_token += 1
    self._hq_token += 1
    self._loading_path = None
    self._loading_token = None
    for thread, _worker in list(self._active_threads.values()):
        thread.quit()
        thread.wait(timeout_ms)
    for thread, _worker in list(self._hq_threads.values()):
        thread.quit()
        thread.wait(timeout_ms)
```

- [ ] **Step 6: Run HQ tests — expect PASS**

```bash
D:/miniforge3/envs/tool/python.exe -m unittest \
  tests.FAKESECRET_u3v4w5x6y7z8a9b0c1d2 \
  tests.FAKESECRET_s1t2u3v4w5x6y7z8a9b0 \
  tests.FAKESECRET_c2d3e4f5g6h7i8j9k0l1 \
  -v
```

Expected: PASS

If `test_viewer_idle_settle_replaces_pixmap_with_hq_resize` is flaky because fit scale ≈ 1 on offscreen sizing, keep the 2000×1000 source and 400×300 view; do not shrink the source in the test.

- [ ] **Step 7: Run full Qt workbench suite**

```bash
D:/miniforge3/envs/tool/python.exe -m unittest tests.test_qt_workbench -v
```

Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add qt_image_viewer.py tests/test_qt_workbench.py
git commit -m "$(cat <<'EOF'
feat(viewer): lanczos settle pass after interactive zoom

Keep matrix zoom for responsiveness, then resample the source
image to on-screen size once the wheel is idle.
EOF
)"
```

---

### Task 4: Manual Quality / Performance Smoke

**Files:**
- None (manual verification only)

- [ ] **Step 1: Launch Qt app**

```bash
D:/miniforge3/envs/tool/python.exe qt_main.py
```

- [ ] **Step 2: Verify interactive feel (must match current)**

1. Open a real batch with at least one 8–24MP image (or any large photo).
2. Ctrl+wheel zoom in/out rapidly.
3. Drag pan.
4. Confirm: no multi-hundred-ms hitch **during** wheel ticks (matrix path only).

- [ ] **Step 3: Verify idle quality (must improve)**

1. Fit image to window (toolbar Fit / double-click).
2. Wait ~0.2s after stopping.
3. Compare edges/text against memory of previous Qt nearest-neighbor look.
4. Zoom to ~2× fit, stop, wait settle; edges should soften vs old hard pixels and look closer to Tk.
5. Zoom again immediately: image may briefly return to source display (expected) then re-settle.

- [ ] **Step 4: Verify no jump / no stale frames**

1. Settle at a zoom level; note a distinct feature under the cursor/center.
2. Confirm settle does not visibly teleport the feature.
3. Spam Ctrl+wheel, then quickly navigate to next image: no crash, no old image HQ popping in.

- [ ] **Step 5: Optional Tk side-by-side**

If practical, open same image in `main.py` Tk tool and compare settled zoom quality. Qt need not be pixel-identical; it should be in the same quality class (no harsh aliasing when idle).

- [ ] **Step 6: Record outcome in commit message or PR notes only if issues found**

If settle is too slow on target machines:

- First optimize `_qimage_to_pil` to raw buffer conversion (no PNG).
- Only if still insufficient, open a follow-up for a Fast/Quality toggle (out of scope here).

No code commit required if manual smoke passes.

---

### Task 5: Final Regression Sweep

**Files:**
- None unless failures require fixes

- [ ] **Step 1: Run focused + full tests**

```bash
D:/miniforge3/envs/tool/python.exe -m unittest tests.test_qt_workbench -v
D:/miniforge3/envs/tool/python.exe -m unittest tests.test_classifier_core -v
```

Expected: all PASS

- [ ] **Step 2: If any test failed due to HQ timing, fix by:**

- Using `_finish_zoom_interaction()` directly instead of waiting on the 140ms timer in tests
- Waiting on `not viewer._hq_threads` with `_process_events_until`
- Never sleeping fixed long durations unless as last resort

- [ ] **Step 3: Final commit only if Task 5 required code fixes**

```bash
git add qt_image_viewer.py tests/test_qt_workbench.py
git commit -m "$(cat <<'EOF'
fix(viewer): stabilize HQ settle tests and edge cases
EOF
)"
```

---

## Implementation Notes / Pitfalls

1. **`_fit_scale` must be measured on source display** (`_display_scale == 1.0`). Always `_ensure_source_display()` before `fitInView` / before min-max zoom math.
2. **Do not HQ on every wheel event** — only on timer settle / explicit `_finish_zoom_interaction`.
3. **Token rules:** bump `_hq_token` on: new load, clear, shutdown, interactive zoom start, fit, and when starting a new HQ job. Apply path ignores mismatched tokens.
4. **Preserve-view mode:** still schedule HQ after load so the kept zoom level gets a clean settle.
5. **Existing test rewrite is intentional:** `test_viewer_uses_sharp_rendering_at_high_zoom_and_smooth_fit` encoded the old anti-smooth policy; replacing it is part of the product change, not collateral damage.
6. **Antialiasing** can stay off (`Antialiasing=False`); it is for shapes/text, not the main pixmap quality lever.
7. **Python interpreter:** always `D:/miniforge3/envs/tool/python.exe` per project `CLAUDE.md`.

## Acceptance Criteria

- [ ] Interactive Ctrl+wheel zoom remains matrix-based and feels as responsive as current Qt.
- [ ] `QGraphicsPixmapItem` uses `SmoothTransformation` at fit and high zoom.
- [ ] After idle settle, displayed pixmap resolution tracks on-screen size (not only view scale on full-res pixels).
- [ ] Settle uses Pillow LANCZOS (or documented equivalent if swapped during optimization).
- [ ] Stale HQ results never overwrite a newer zoom/image.
- [ ] Effective scale before/after HQ apply matches within test tolerance; no obvious jump in manual smoke.
- [ ] No new user-facing mode switch in v1.
- [ ] `tests.test_qt_workbench` passes offscreen.

## Follow-ups (explicitly not in this plan)

- Fast/Quality toolbar toggle + `config.json` persistence
- Raw QImage↔Pillow conversion without PNG encode
- Mipmap pyramid cache for repeated zooms on the same image
- Device-pixel-ratio / HiDPI-aware HQ sizing

## Self-Review

1. **Spec coverage:** default quality up without losing speed → Tasks 1–3; no mode switch → locked in Design; cancel/token → Task 3; manual UX → Task 4.
2. **Placeholders:** none; concrete tests, methods, and commands included.
3. **Type/name consistency:** `_source_image`, `_display_scale`, `_hq_token`, `_hq_threads`, `_finish_zoom_interaction`, `_start_hq_resize`, `_handle_hq_resized`, `_swap_pixmap_preserving_view`, `_ensure_source_display`, `_target_hq_size` used consistently across tasks.
