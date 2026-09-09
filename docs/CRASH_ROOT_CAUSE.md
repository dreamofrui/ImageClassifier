# 崩溃根本原因分析

## 崩溃位置

**确切位置：`_abort_hq()` 在处理 `active_hq=1` 时崩溃**

最后的日志：
```
10:26:55.035 [MainThread] >>> _handle_image_loaded | token=728
10:26:55.035 [MainThread]     [_handle_image_loaded] preserve_view=True
10:26:55.035 [MainThread] >>> _abort_hq | old_token=1953, active_hq=1
[崩溃 - 无后续日志]
```

## 崩溃时的状态

### 活跃线程状态
- **HQ线程1952**：正在被取消（10:26:55.026 cancelled_late）
- **图片加载线程728**：刚完成（10:26:55.026 success）
- **MainThread**：在 `_handle_image_loaded` 中调用 `_abort_hq()`

### 关键时间线（崩溃前1秒）

```
10:26:54.945 >>> load_image token=728 (触发 _abort_hq token=1952, active_hq=1)
10:26:54.953 [Thread-728] ImageLoad.start
10:26:55.026 [Thread-1952] HqResize.cancelled_late  ← HQ线程报告取消
10:26:55.026 [Thread-728] ImageLoad.success         ← 图片加载完成
10:26:55.034 >>> _handle_hq_resized token=1952 (忽略，token不匹配)
10:26:55.035 >>> _handle_image_loaded token=728    ← 开始处理新图片
10:26:55.035 >>> _abort_hq | active_hq=1            ← 崩溃点
```

## 根本原因

### 竞争条件：HQ线程的finished信号与_prune_hq_threads

**问题序列：**

1. **10:26:54.945** - `load_image(728)` 调用 `_abort_hq()`
   - `_hq_token` 从1952增加到1953
   - 调用 `_prune_hq_threads(request_stop=True)`
   - 对线程1952调用 `worker.cancel()` 和 `thread.quit()`

2. **10:26:55.026** - 线程1952检测到取消并退出
   - 发射 `finished` 信号（带参数 token=1952, error="cancelled"）
   - 线程即将终止

3. **10:26:55.034** - `_handle_hq_resized(token=1952)` 被调用
   - Token不匹配，正确忽略
   - **但 `thread.finished` 信号即将触发 `thread.deleteLater()`**

4. **10:26:55.035** - `_handle_image_loaded(token=728)` 开始执行
   - 调用 `_abort_hq(old_token=1953, active_hq=1)`
   - `_prune_hq_threads(request_stop=True)` 被调用
   - 尝试访问 `self._hq_threads[1952]` 的 `(thread, worker)`
   - **此时C++ QThread对象可能已被 `deleteLater()` 标记删除**
   - 调用 `thread.isRunning()` 或 `worker.cancel()` 时触发 **RuntimeError 或段错误**

### 代码证据

```python
# qt_image_viewer.py:437-452
def _prune_hq_threads(self, request_stop: bool = False) -> None:
    for token, (thread, worker) in list(self._hq_threads.items()):
        try:
            running = thread.isRunning()  # ← 可能崩溃：C++对象已被deleteLater
        except RuntimeError:
            self._hq_threads.pop(token, None)
            continue
        if running:
            if request_stop:
                try:
                    worker.cancel()      # ← 或这里崩溃
                    thread.quit()
                except RuntimeError:
                    pass
```

**问题：**
1. `thread.finished` 信号触发后，`deleteLater()` 被调用
2. Qt事件循环可能在同一事件处理中删除C++对象
3. `_prune_hq_threads` 尝试访问已删除的C++对象
4. **虽然有 `try-except RuntimeError`，但段错误（SIGSEGV）无法被Python捕获**

## 为什么没有Python异常日志

**段错误（Segmentation Fault）不会产生Python异常：**
- 访问已删除的C++ QThread对象触发CPU级别的访问违规
- 操作系统直接终止进程
- Python解释器无法捕获，也无法记录日志

## 修复方案

### 方案A：立即清理finished线程（推荐）

在 `_handle_hq_thread_finished` 中立即从字典移除：

```python
def _handle_hq_thread_finished(self, token: int) -> None:
    # 立即清除，防止_prune访问已删除对象
    self._hq_threads.pop(token, None)
    
    if token == self._hq_token or self._hq_threads:
        return
    if self._has_image and self._loading_path is None:
        self._schedule_hq_settle()
```

**原理：**
- `thread.finished` 触发后立即从 `_hq_threads` 移除
- `_prune_hq_threads` 不会看到这个线程
- 避免访问即将删除的C++对象

### 方案B：改进_prune的安全性

在访问thread/worker前检查C++对象有效性：

```python
def _prune_hq_threads(self, request_stop: bool = False) -> None:
    for token, (thread, worker) in list(self._hq_threads.items()):
        # 先检查对象是否仍然有效
        thread_valid = self._is_qobject_valid(thread)
        worker_valid = self._is_qobject_valid(worker)
        
        if not thread_valid or not worker_valid:
            self._hq_threads.pop(token, None)
            continue
            
        # 后续操作...
```

### 方案C：禁止_abort_hq在image_loaded期间调用

使用标志保护：

```python
def _handle_image_loaded(self, ...):
    self._in_image_loaded = True
    try:
        # ... 现有逻辑，但跳过 _abort_hq()
    finally:
        self._in_image_loaded = False
        self._abort_hq()  # 在最后统一调用
```

## 推荐修复

**方案A最简单可靠**，因为：
1. 修改最小（只改一个地方）
2. 逻辑清晰（finished线程立即清理）
3. 避免了根本的竞争条件

立即实施方案A。
