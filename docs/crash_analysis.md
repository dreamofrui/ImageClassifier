# 图片快速切换崩溃问题分析

## 问题描述
用户在快速切换图片并进行分类操作时，应用会突然卡住然后崩溃退出，控制台无任何错误日志。

## 根本原因分析

### 1. **主要竞争条件：HQ渲染线程与图片切换**

#### 问题路径：
```
用户操作：快速滚轮切换 + 点击分类按钮
↓
wheelEvent (line 604-628) → _abort_hq() → wheel_navigation_requested.emit()
↓
next_image() → _set_current_image_index() → _load_current_image() → load_image()
↓
load_image() (line 193-220) → _abort_hq() → _start_image_load()
↓
同时：_handle_hq_resized() (line 588-602) 正在执行
↓
_swap_pixmap_preserving_view() (line 506-534) 访问Qt对象
```

#### 具体竞争窗口：

**位置1：`_swap_pixmap_preserving_view` 中的Qt对象访问**
```python
# qt_image_viewer.py:520-534
anchor_view = self.viewport().rect().center()  # ← 可能在这里崩溃
anchor_scene = self.mapToScene(anchor_view)    # ← 或这里
source_x = anchor_scene.x() / old_display_scale
source_y = anchor_scene.y() / old_display_scale

self._pixmap_item.setPixmap(pixmap)  # ← 或这里
self.setSceneRect(QRectF(pixmap.rect()))
self.setTransform(QTransform.fromScale(new_view_scale, new_view_scale))
self.centerOn(QPointF(...))  # ← 或这里
```

**问题**：当 `_handle_hq_resized()` 正在执行 `_swap_pixmap_preserving_view()` 时：
- 主线程调用 `load_image()` → `_abort_hq()` 增加 `_hq_token`
- `_handle_hq_resized` 的token检查（line 592）通过（因为它在token增加前就开始执行）
- 但随后 `load_image()` 继续执行，可能在 `_swap_pixmap_preserving_view()` 执行到一半时：
  - 调用 `resetTransform()` (line 210, 263)
  - 调用 `setSceneRect()` (line 363)
  - 这导致 `_swap_pixmap_preserving_view()` 中的 `mapToScene()` 和 `setTransform()` 操作基于已失效的变换状态

**位置2：`_handle_image_loaded` 与 `_handle_hq_resized` 竞争**
```python
# _handle_image_loaded (line 326-381)
preserved_effective = max(self.transform().m11(), 1e-6) * max(
    self._display_scale, 1e-6
)  # ← 读取当前状态

# 如果此时 _handle_hq_resized 在另一个事件循环周期中执行：
# _swap_pixmap_preserving_view 修改了 transform 和 _display_scale

self._source_image = image  # ← 替换源图像
self._display_scale = 1.0   # ← 重置 display_scale
# ... 后续使用 preserved_effective 恢复视图时，状态已不一致
```

### 2. **次要竞争：分类操作与图片加载**

```python
# qt_workbench.py:1216-1240
def classify(self, key: str, enforce_focus: bool = False) -> None:
    current = self.session.current_image()
    if current is not None and self.image_viewer.is_loading_path(current):
        self._set_status("Image is still loading")
        return  # ← 检查时是loading，但下一行可能就完成了
    
    # ... 启动分类移动操作（在后台线程）
    self._run_move_operation(
        self.session.classify_current,
        self._handle_classify_finished,
        key,
    )

# _handle_classify_finished (line 1571-1588)
def _handle_classify_finished(self, record, error):
    # ...
    self._sync_after_session_change(f"Moved to {record.category}")
    # ↓
    # _sync_after_session_change → _load_current_image → load_image
```

**时序问题**：
1. 用户快速按键：分类A → 分类B → next_image
2. 分类A的 `_run_move_operation` 在后台线程执行
3. 用户继续操作，触发分类B和next_image
4. 分类A完成回调 → `_sync_after_session_change` → `load_image(imageA)`
5. 但此时用户已经在看imageC了，突然加载imageA导致状态混乱

### 3. **Qt对象生命周期问题**

```python
# qt_image_viewer.py:285-297
for thread, worker in list(self._hq_threads.values()):
    try:
        worker.cancel()  # ← threading.Event.set()
    except RuntimeError:  # ← C++对象已销毁
        pass
    try:
        thread.quit()
        if not thread.wait(timeout_ms):
            thread.wait()
    except RuntimeError:  # ← C++对象已销毁
        pass
```

**问题**：`deleteLater()` 导致C++对象可能在Python还持有引用时被销毁，访问时触发段错误（无Python异常）。

### 4. **无日志的原因**

崩溃发生在：
1. **Qt事件循环中的C++层**：段错误/访问违规不会被Python捕获
2. **QThread的信号/槽机制**：跨线程信号在Qt内部排队，崩溃发生在Qt元对象系统
3. **QGraphicsView的变换矩阵计算**：数学运算时除零或无效矩阵

## 修复方案

### 方案1：加强HQ渲染的原子性保护（推荐）

**目标**：确保 `_swap_pixmap_preserving_view()` 执行期间不会被 `load_image()` 打断

**实现**：
1. 添加 `_swapping_pixmap` 标志
2. `load_image()` 检查此标志，如果正在交换则延迟
3. `_swap_pixmap_preserving_view()` 使用try-finally保证标志清除

### 方案2：改进token验证时机

**目标**：token验证应该在修改Qt对象前立即进行，而非在函数开始时

### 方案3：防止分类操作完成回调时的图片回跳

**目标**：分类完成回调不应该重新加载已经离开的图片

## 推荐修复优先级

1. **P0** - 修复 `_swap_pixmap_preserving_view()` 的原子性问题
2. **P0** - 在 `_handle_classify_finished` 中防止图片回跳
3. **P1** - 改进 `_handle_hq_resized` 的token验证时机
4. **P2** - 增强 `_abort_hq()` 的等待机制（可选，影响性能）
