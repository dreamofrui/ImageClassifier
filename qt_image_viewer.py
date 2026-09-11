import threading
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap, QTransform, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
)

from viewer_debug import get_debug_logger

_debug = get_debug_logger()


def _qimage_raw_rgba_bytes(image: QImage) -> tuple[bytes, int, int]:
    """Return tightly packed RGBA8888 bytes plus width/height."""
    rgba = image
    if rgba.format() != QImage.Format.Format_RGBA8888:
        rgba = rgba.convertToFormat(QImage.Format.Format_RGBA8888)
    width = rgba.width()
    height = rgba.height()
    if width <= 0 or height <= 0:
        return b"", 0, 0

    raw = bytes(rgba.constBits())
    bpl = rgba.bytesPerLine()
    row_bytes = width * 4
    if bpl == row_bytes:
        return raw, width, height

    packed = bytearray(row_bytes * height)
    for y in range(height):
        start = y * bpl
        packed[y * row_bytes : (y + 1) * row_bytes] = raw[start : start + row_bytes]
    return bytes(packed), width, height


def _lanczos_resize(source: QImage, width: int, height: int) -> QImage:
    """Resize with Pillow LANCZOS using raw pixel buffers (no PNG round-trip)."""
    from PIL import Image

    if width <= 0 or height <= 0 or source.isNull():
        return QImage()

    src_bytes, src_w, src_h = _qimage_raw_rgba_bytes(source)
    if not src_bytes or src_w <= 0 or src_h <= 0:
        return QImage()

    pil = Image.frombytes("RGBA", (src_w, src_h), src_bytes)
    resized = pil.resize((width, height), Image.Resampling.LANCZOS)
    out_bytes = resized.tobytes()

    # QImage(bytes, w, h, format) keeps a reference to the buffer object.
    buffer = bytes(out_bytes)
    out = QImage(buffer, width, height, width * 4, QImage.Format.Format_RGBA8888)
    # Detach so the image owns its own memory after this function returns.
    return out.copy()


class _ImageLoadWorker(QObject):
    finished = Signal(object, int, object, str)

    def __init__(self, path: Path, token: int):
        super().__init__()
        self._path = Path(path)
        self._token = token

    @Slot()
    def run(self) -> None:
        _debug.log_thread_event(
            "ImageLoad.start", self._token, path=self._path.name
        )
        try:
            image_data = self._path.read_bytes()
        except OSError as exc:
            _debug.log_thread_event(
                "ImageLoad.read_failed", self._token, error=str(exc)
            )
            self.finished.emit(
                self._path,
                self._token,
                QImage(),
                f"Unable to read image: {self._path.name} ({exc})",
            )
            return

        image = QImage()
        if not image.loadFromData(image_data):
            _debug.log_thread_event(
                "ImageLoad.decode_failed", self._token, path=self._path.name
            )
            self.finished.emit(
                self._path,
                self._token,
                QImage(),
                f"Unable to load image: {self._path.name}",
            )
            return

        _debug.log_thread_event(
            "ImageLoad.success", self._token, size=f"{image.width()}x{image.height()}"
        )
        self.finished.emit(self._path, self._token, image.copy(), "")


class _HqResizeWorker(QObject):
    finished = Signal(int, object, float, str)  # token, QImage, display_scale, error

    def __init__(
        self, token: int, source: QImage, width: int, height: int, source_width: int
    ):
        super().__init__()
        self._token = token
        self._source = source
        self._width = width
        self._height = height
        self._source_width = max(source_width, 1)
        self._cancel_requested = threading.Event()

    def cancel(self) -> None:
        self._cancel_requested.set()

    @Slot()
    def run(self) -> None:
        _debug.log_thread_event(
            "HqResize.start", self._token, target=f"{self._width}x{self._height}"
        )
        try:
            if self._cancel_requested.is_set():
                _debug.log_thread_event("HqResize.cancelled_early", self._token)
                self._source = QImage()
                self.finished.emit(self._token, QImage(), 1.0, "cancelled")
                return

            resized = _lanczos_resize(self._source, self._width, self._height)
            self._source = QImage()

            if self._cancel_requested.is_set():
                _debug.log_thread_event("HqResize.cancelled_late", self._token)
                self.finished.emit(self._token, QImage(), 1.0, "cancelled")
                return

            if resized.isNull():
                _debug.log_thread_event("HqResize.failed", self._token)
                self.finished.emit(self._token, QImage(), 1.0, "HQ resize failed")
                return

            display_scale = self._width / float(self._source_width)
            _debug.log_thread_event(
                "HqResize.success", self._token, scale=f"{display_scale:.3f}"
            )
            self.finished.emit(self._token, resized, display_scale, "")
        except Exception as exc:  # noqa: BLE001 - surface to UI path
            _debug.log_error(f"HqResize.exception token={self._token}", exc)
            self._source = QImage()
            self.finished.emit(self._token, QImage(), 1.0, str(exc))


class ImageViewer(QGraphicsView):
    wheel_navigation_requested = Signal(int)

    # Max retries for a failing HQ resize before giving up (exponential
    # backoff 140/280/560 ms) -- a persistently failing resize must not
    # re-run a full Lanczos every 140 ms forever.
    _HQ_RETRY_MAX = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._pixmap_item = QGraphicsPixmapItem()
        self._pixmap_item.setTransformationMode(
            Qt.TransformationMode.SmoothTransformation
        )
        self._message_item = QGraphicsTextItem()
        self._load_token = 0
        self._active_threads = {}
        self._pending_load = None
        self._shutting_down = False
        self._loading_path = None
        self._loading_token = None
        self._has_image = False
        self._preserve_view = False
        self._fit_mode = True
        self._fit_scale = 1.0
        self._min_zoom_ratio = 0.05
        self._max_zoom_ratio = 12.0
        self._source_image = None
        self._source_width = 0
        self._display_scale = 1.0
        self._hq_token = 0
        # Thread tracking for shutdown(): entries live until thread.finished
        # (NOT worker-finished -- the window between the two is exactly where
        # a destroyed-but-running QThread caused crashes).
        self._hq_threads = {}
        # Single-flight state: the token of the one HQ job that is computing
        # or awaiting result delivery. Set in _start_hq_resize, cleared when
        # the job's finished signal reaches _handle_hq_resized.
        self._hq_active_token = None
        self._max_hq_edge = 8192
        self._hq_scale_epsilon = 0.01
        self._zoom_quality_timer = QTimer(self)
        self._zoom_quality_timer.setSingleShot(True)
        self._zoom_quality_timer.setInterval(140)
        self._zoom_quality_timer.timeout.connect(self._finish_zoom_interaction)
        self._hq_retry_count = 0
        self._hq_retry_timer = QTimer(self)
        self._hq_retry_timer.setSingleShot(True)
        self._hq_retry_timer.timeout.connect(self._finish_zoom_interaction)

        self.setScene(self._scene)
        self._scene.addItem(self._pixmap_item)
        self._scene.addItem(self._message_item)

        self._message_item.setDefaultTextColor(QColor("#c7ccd4"))
        self._message_item.setPlainText("No image loaded")
        font = self._message_item.font()
        font.setPointSize(11)
        font.setWeight(QFont.Weight.DemiBold)
        self._message_item.setFont(font)
        self._message_item.setZValue(1)
        self._set_message_visible(True)

        self.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setBackgroundBrush(QColor("#111418"))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def load_image(self, path: Path) -> None:
        if self._shutting_down:
            return

        self._load_token += 1
        self._abort_hq()
        token = self._load_token
        image_path = Path(path)

        _debug.log_operation(
            "load_image",
            token=token,
            path=image_path.name,
            has_image=self._has_image,
            active_threads=len(self._active_threads),
            hq_threads=len(self._hq_threads),
        )

        has_visible_image = self._has_image and not self._pixmap_item.pixmap().isNull()
        if not has_visible_image:
            self._has_image = False
        self._loading_path = image_path
        self._loading_token = token
        if not has_visible_image:
            self._pixmap_item.setPixmap(QPixmap())
        if not self._preserve_view and not has_visible_image:
            self.resetTransform()
            self._fit_mode = True
            self._fit_scale = 1.0
            self._display_scale = 1.0
        self._set_message_visible(False)

        if self._active_threads:
            _debug.log_state("load_image", action="defer", reason="active_threads")
            self._pending_load = (image_path, token)
            return

        self._start_image_load(image_path, token)

    def _start_image_load(self, image_path: Path, token: int) -> None:
        thread = QThread(self)
        worker = _ImageLoadWorker(image_path, token)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(self._handle_image_loaded)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # Bound slot (not a lambda): receiver affinity is explicitly self, so
        # the queued call is guaranteed to land on the main thread regardless
        # of PySide's proxy-affinity semantics for plain callables. This keeps
        # dict mutation and QThread construction single-threaded.
        thread.finished.connect(self._handle_load_thread_finished)

        self._active_threads[token] = (thread, worker)
        thread.start()

    @Slot()
    def _handle_load_thread_finished(self) -> None:
        sender = self.sender()
        for token, (thread, _worker) in list(self._active_threads.items()):
            if thread is sender:
                self._active_threads.pop(token, None)
                break
        if self._shutting_down or self._pending_load is None:
            return

        image_path, pending_token = self._pending_load
        self._pending_load = None
        if pending_token != self._load_token:
            return
        self._start_image_load(image_path, pending_token)

    def clear(self, message: str = "No image loaded") -> None:
        self._load_token += 1
        self._abort_hq()
        self._pending_load = None
        self._has_image = False
        self._loading_path = None
        self._loading_token = None
        self._source_image = None
        self._source_width = 0
        self._display_scale = 1.0
        self._pixmap_item.setPixmap(QPixmap())
        self.resetTransform()
        self._fit_mode = True
        self._fit_scale = 1.0
        self._show_message(message)

    def is_loading_path(self, path: Path) -> bool:
        return self._loading_path == Path(path)

    def shutdown(self, timeout_ms: int = 1500) -> None:
        self._shutting_down = True
        self._load_token += 1
        self._abort_hq()
        self._pending_load = None
        self._loading_path = None
        self._loading_token = None
        for thread, _worker in list(self._active_threads.values()):
            try:
                thread.quit()
                if not thread.wait(timeout_ms):
                    # Bounded wait only: never block the main thread forever on
                    # a stuck worker. The late result is discarded via token check.
                    _debug.log_warning(
                        "Load thread did not stop in time; leaving it running",
                        timeout_ms=timeout_ms,
                    )
            except (RuntimeError, AttributeError):
                pass
        self._active_threads.clear()
        for thread, worker in list(self._hq_threads.values()):
            try:
                worker.cancel()
            except (RuntimeError, AttributeError):
                pass
            try:
                thread.quit()
                if not thread.wait(timeout_ms):
                    _debug.log_warning(
                        "HQ thread did not stop in time; leaving it running",
                        timeout_ms=timeout_ms,
                    )
            except (RuntimeError, AttributeError):
                pass
        self._hq_threads.clear()
        self._hq_active_token = None

    def fit_to_window(self) -> None:
        if not self._has_image:
            self._center_message()
            return

        self._abort_hq()
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

    def reset_view(self) -> None:
        self.fit_to_window()

    def set_preserve_view(self, enabled: bool) -> None:
        self._preserve_view = enabled

    @Slot(object, int, object, str)
    def _handle_image_loaded(
        self, path: Path, token: int, image: QImage, error: str
    ) -> None:
        _debug.log_operation(
            "_handle_image_loaded",
            token=token,
            current_token=self._load_token,
            path=path.name,
            has_error=bool(error),
            image_valid=not image.isNull(),
        )

        if token != self._load_token:
            _debug.log_state("_handle_image_loaded", action="ignore", reason="token_mismatch")
            return

        self._loading_path = None
        self._loading_token = None

        if error:
            _debug.log_warning("Image load error", error=error)
            self._has_image = False
            self._source_image = None
            self._source_width = 0
            self._display_scale = 1.0
            self._abort_hq()
            self._pixmap_item.setPixmap(QPixmap())
            self._show_message(error)
            return

        # Worker already emitted a detached copy; avoid a second full-frame copy.
        # Capture effective scale before we replace the pixmap / display_scale.
        preserved_effective = None
        if self._preserve_view and self._has_image:
            preserved_effective = max(self.transform().m11(), 1e-6) * max(
                self._display_scale, 1e-6
            )
            _debug.log_state(
                "_handle_image_loaded",
                preserve_view=True,
                preserved_effective=f"{preserved_effective:.4f}",
            )

        self._source_image = image
        self._source_width = image.width()
        self._display_scale = 1.0
        self._hq_retry_count = 0  # new image: fresh retry budget
        self._abort_hq()

        _debug.log_state(
            "_handle_image_loaded",
            action="create_pixmap",
            size=f"{image.width()}x{image.height()}",
        )
        pixmap = QPixmap.fromImage(self._source_image)
        self._pixmap_item.setPixmap(pixmap)
        self._pixmap_item.setOffset(0, 0)
        self._has_image = True
        self._set_message_visible(False)
        self.setSceneRect(QRectF(pixmap.rect()))

        if not self._preserve_view:
            _debug.log_state("_handle_image_loaded", action="fit_to_window")
            self.fit_to_window()
        else:
            # Keep Zoom: restore the previous effective on-screen scale on the
            # new source pixmap. Without this, a prior HQ display_scale (e.g.
            # 0.4) is reset to 1.0 while view_scale stays ~1.0, so the image
            # jumps larger and the next HQ job targets a much bigger buffer.
            if preserved_effective is not None:
                _debug.log_state(
                    "_handle_image_loaded",
                    action="restore_view",
                    preserved=f"{preserved_effective:.4f}",
                )
                self._fit_mode = False
                self.setTransform(
                    QTransform.fromScale(preserved_effective, preserved_effective)
                )
            else:
                # First image with Keep Zoom already on — still need a baseline.
                _debug.log_state("_handle_image_loaded", action="fit_first_image")
                self.fit_to_window()
                return
            self._update_render_quality(interactive=False)
            self._schedule_hq_settle()

    def zoom_by(self, factor: float) -> None:
        if not self._has_image or factor <= 0:
            return

        self._abort_hq()
        self._ensure_source_display()

        current_scale = max(self.transform().m11(), 0.01)
        fit_scale = max(self._fit_scale, 0.01)
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

    def _finish_zoom_interaction(self) -> None:
        self._update_render_quality(interactive=False)
        if self._loading_path is not None or self._pending_load is not None:
            return
        self._start_hq_resize()

    def _schedule_hq_settle(self) -> None:
        if (
            self._shutting_down
            or self._loading_path is not None
            or self._pending_load is not None
        ):
            self._zoom_quality_timer.stop()
            return
        self._zoom_quality_timer.start()

    def _schedule_hq_retry(self) -> None:
        """Retry a failed HQ resize with exponential backoff, then give up.

        Without this, a persistently failing resize (PIL exception, null
        result) re-ran a full Lanczos plus a main-thread full-frame copy
        every 140 ms forever.
        """
        self._hq_retry_count += 1
        if self._hq_retry_count > self._HQ_RETRY_MAX:
            _debug.log_warning(
                "HQ resize failed repeatedly; giving up",
                attempts=self._hq_retry_count,
            )
            self._hq_retry_count = 0
            return
        interval_ms = 140 * (2 ** (self._hq_retry_count - 1))  # 140/280/560
        self._hq_retry_timer.start(interval_ms)

    def _abort_hq(self) -> None:
        """Invalidate in-flight HQ and stop settle timer without blocking the UI."""
        _debug.log_operation(
            "_abort_hq",
            old_token=self._hq_token,
            active_hq=len(self._hq_threads),
        )
        self._zoom_quality_timer.stop()
        self._hq_retry_timer.stop()
        self._hq_token += 1
        self._hq_active_token = None
        for _token, (thread, worker) in list(self._hq_threads.items()):
            try:
                worker.cancel()  # pure-Python Event.set -- no C++ boundary cost
            except (RuntimeError, AttributeError):
                self._hq_threads.pop(_token, None)

    def _handle_hq_thread_finished(self) -> None:
        """Pop the dict entry whose QThread just finished (queued to main thread).

        Connected to thread.finished BEFORE thread.deleteLater, so the entry
        is removed before the C++ object is destroyed in the same event-loop
        pass -- a later stale lookup can never see a dead wrapper.
        """
        sender = self.sender()
        for token, (thread, _worker) in list(self._hq_threads.items()):
            if thread is sender:
                self._hq_threads.pop(token, None)
                return

    def _current_zoom_ratio(self) -> float:
        fit_scale = max(self._fit_scale, 0.01)
        effective = max(self.transform().m11(), 0.01) * max(self._display_scale, 0.01)
        return effective / fit_scale

    def _update_render_quality(self, interactive: bool) -> None:
        # interactive reserved for future fast-path tweaks; v1 always smooths.
        del interactive
        self._pixmap_item.setTransformationMode(
            Qt.TransformationMode.SmoothTransformation
        )
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    def _ensure_source_display(self) -> None:
        if self._source_image is None or self._source_image.isNull():
            return
        if abs(self._display_scale - 1.0) < 1e-6:
            return
        source_pixmap = QPixmap.fromImage(self._source_image)
        self._swap_pixmap_preserving_view(source_pixmap, 1.0)

    def _target_hq_size(self):
        if self._source_image is None or self._source_image.isNull():
            return None
        src_w = self._source_image.width()
        src_h = self._source_image.height()
        if src_w <= 0 or src_h <= 0:
            return None

        effective = max(self.transform().m11(), 1e-6) * max(self._display_scale, 1e-6)
        # At or above 1:1, the full-res source already has enough pixels for the
        # screen; LANCZOS upscale only burns CPU/RAM and can freeze the process.
        if effective >= 1.0 - self._hq_scale_epsilon:
            return None

        target_w = max(1, int(round(src_w * effective)))
        target_h = max(1, int(round(src_h * effective)))

        longest = max(target_w, target_h)
        if longest > self._max_hq_edge:
            clamp = self._max_hq_edge / float(longest)
            target_w = max(1, int(round(target_w * clamp)))
            target_h = max(1, int(round(target_h * clamp)))

        current_w = self._pixmap_item.pixmap().width()
        if current_w > 0:
            ratio = target_w / float(current_w)
            if abs(ratio - 1.0) <= self._hq_scale_epsilon:
                return None

        return target_w, target_h

    def _swap_pixmap_preserving_view(
        self, pixmap: QPixmap, new_display_scale: float
    ) -> None:
        if pixmap.isNull() or not self._has_image:
            return

        _debug.log_operation(
            "_swap_pixmap_preserving_view",
            old_scale=f"{self._display_scale:.4f}",
            new_scale=f"{new_display_scale:.4f}",
            pixmap_size=f"{pixmap.width()}x{pixmap.height()}",
        )

        old_display_scale = max(self._display_scale, 1e-6)
        old_view_scale = max(self.transform().m11(), 1e-6)
        effective = old_view_scale * old_display_scale

        # Preserve the source-image point currently under the viewport center.
        # Must not use self.scale() here: transformationAnchor is AnchorUnderMouse,
        # so scale() after resetTransform() re-anchors under the cursor and jumps
        # the view (reads as an extra zoom/pan after idle settle).
        try:
            anchor_view = self.viewport().rect().center()
            anchor_scene = self.mapToScene(anchor_view)
            source_x = anchor_scene.x() / old_display_scale
            source_y = anchor_scene.y() / old_display_scale
            _debug.log_state(
                "_swap_pixmap",
                anchor=f"({source_x:.1f}, {source_y:.1f})",
            )
        except Exception as exc:
            _debug.log_error("_swap_pixmap anchor calculation failed", exc)
            raise

        try:
            self._pixmap_item.setPixmap(pixmap)
            self._pixmap_item.setOffset(0, 0)
            self.setSceneRect(QRectF(pixmap.rect()))
            self._display_scale = max(new_display_scale, 1e-6)

            new_view_scale = effective / self._display_scale
            self.setTransform(QTransform.fromScale(new_view_scale, new_view_scale))
            self.centerOn(
                QPointF(source_x * self._display_scale, source_y * self._display_scale)
            )
            _debug.log_state("_swap_pixmap", status="success")
        except Exception as exc:
            _debug.log_error("_swap_pixmap Qt operations failed", exc)
            raise

    def _start_hq_resize(self) -> None:
        if (
            self._shutting_down
            or self._loading_path is not None
            or self._pending_load is not None
            or not self._has_image
            or self._source_image is None
            or self._source_image.isNull()
        ):
            return

        # Cap concurrent HQ work. A stale job's finished handler schedules one
        # retry for the current image, avoiding a 140 ms polling loop.
        # (_hq_threads is shutdown bookkeeping only -- entries outlive the job
        # until thread.finished, so single-flight state lives in _hq_active_token.)
        if self._hq_active_token is not None:
            _debug.log_state("_start_hq_resize", action="skip", reason="thread_running")
            return

        target = self._target_hq_size()
        if target is None:
            return
        target_w, target_h = target
        src_w = max(self._source_width, self._source_image.width(), 1)

        self._hq_token += 1
        token = self._hq_token
        source_copy = self._source_image.copy()

        _debug.log_operation(
            "_start_hq_resize",
            token=token,
            target=f"{target_w}x{target_h}",
            source=f"{src_w}x{self._source_image.height()}",
        )

        thread = QThread(self)
        worker = _HqResizeWorker(token, source_copy, target_w, target_h, src_w)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._handle_hq_resized)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)

        # Pop the tracking entry when the THREAD (not the worker) finishes, so
        # shutdown() sees every still-running QThread. Bound slot with receiver
        # self -> queued to the main thread. Ordered before thread.deleteLater
        # so the entry is gone before the C++ object is destroyed.
        thread.finished.connect(self._handle_hq_thread_finished)
        thread.finished.connect(thread.deleteLater)

        self._hq_threads[token] = (thread, worker)
        self._hq_active_token = token
        thread.start()

    @Slot(int, object, float, str)
    def _handle_hq_resized(
        self, token: int, image: QImage, display_scale: float, error: str
    ) -> None:
        _debug.log_operation(
            "_handle_hq_resized",
            token=token,
            current_token=self._hq_token,
            has_error=bool(error),
            image_valid=not (image is None or image.isNull()),
            has_image=self._has_image,
        )

        # Single-flight state: this job is no longer computing.
        if token == self._hq_active_token:
            self._hq_active_token = None

        if token != self._hq_token:
            _debug.log_state("_handle_hq_resized", action="ignore", reason="token_mismatch")
            # Schedule next HQ if needed (this worker is done but was stale)
            if (
                self._hq_active_token is None
                and self._has_image
                and self._loading_path is None
            ):
                self._schedule_hq_settle()
            return
        if error or image is None or image.isNull():
            _debug.log_state("_handle_hq_resized", action="skip", reason=error or "invalid_image")
            # Retry with backoff; gives up after _HQ_RETRY_MAX attempts.
            if (
                self._hq_active_token is None
                and self._has_image
                and self._loading_path is None
            ):
                self._schedule_hq_retry()
            return
        if not self._has_image:
            _debug.log_warning("_handle_hq_resized called but no image loaded")
            return
        if display_scale <= 0:
            src_w = max(self._source_width, 1)
            display_scale = image.width() / float(src_w)

        _debug.log_state(
            "_handle_hq_resized",
            action="swap_pixmap",
            scale=f"{display_scale:.4f}",
            size=f"{image.width()}x{image.height()}",
        )
        pixmap = QPixmap.fromImage(image)
        self._swap_pixmap_preserving_view(pixmap, display_scale)
        self._hq_retry_count = 0  # success: reset backoff for next failure

        # Schedule next HQ task if needed (after this worker completes successfully)
        if self._hq_active_token is None and self._has_image and self._loading_path is None:
            self._schedule_hq_settle()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self._has_image:
            event.ignore()
            return

        delta_y = event.angleDelta().y() or event.pixelDelta().y()
        if delta_y == 0:
            event.ignore()
            return

        if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Cancel pending/running HQ so rapid next/prev does not pile up work.
            _debug.log_operation(
                "wheelEvent.navigation",
                delta=delta_y,
                direction="prev" if delta_y > 0 else "next",
            )
            self._abort_hq()
            direction = -1 if delta_y > 0 else 1
            self.wheel_navigation_requested.emit(direction)
            event.accept()
            return

        if delta_y > 0:
            factor = 1.25
        else:
            factor = 0.8

        _debug.log_operation("wheelEvent.zoom", factor=factor)
        self.zoom_by(factor)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_view()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._has_image and self._fit_mode:
            self.fit_to_window()
        else:
            self._center_message()

    def _show_message(self, message: str) -> None:
        self._message_item.setPlainText(message)
        self._set_message_visible(True)
        self._center_message()

    def _set_message_visible(self, visible: bool) -> None:
        self._message_item.setVisible(visible)
        if visible:
            self._center_message()

    def _center_message(self) -> None:
        viewport_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        if viewport_rect.isNull():
            viewport_rect = QRectF(0, 0, 400, 260)
            self.setSceneRect(viewport_rect)

        text_rect = self._message_item.boundingRect()
        x = viewport_rect.center().x() - text_rect.width() / 2
        y = viewport_rect.center().y() - text_rect.height() / 2
        self._message_item.setPos(QPointF(x, y))
