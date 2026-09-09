# 崩溃修复总结

## 问题定位

**崩溃位置：** `_abort_hq()` → `_prune_hq_threads()` 访问已被 `deleteLater()` 标记删除的C++ QThread对象

**根本原因：** Qt对象生命周期竞争条件
- HQ线程完成后发射 `finished` 信号
- `finished` 信号触发 `thread.deleteLater()`（自动删除C++对象）
- 同时触发 `_handle_hq_thread_finished` lambda回调
- 但在回调执行前，另一个操作调用了 `_abort_hq()`
- `_prune_hq_threads` 尝试访问即将/已经删除的C++ QThread对象
- 触发段错误（SIGSEGV），Python无法捕获，进程直接崩溃

## 实施的修复方案

### 修复1：显式生命周期管理

**改动位置：** `_start_hq_resize()`

```python
# 修改前
thread.finished.connect(thread.deleteLater)  # ❌ 自动删除，时序不可控
thread.finished.connect(lambda: self._handle_hq_thread_finished(token))

# 修改后
thread.finished.connect(lambda: self._cleanup_hq_thread(token))  # ✅ 显式管理
# 移除了 thread.deleteLater 的自动连接
```

**新增方法：** `_cleanup_hq_thread(token)`
```python
def _cleanup_hq_thread(self, token: int) -> None:
    """安全清理已完成的HQ线程，显式控制生命周期"""
    entry = self._hq_threads.pop(token, None)  # 立即从字典移除
    if entry is None:
        return
    thread, worker = entry
    thread.deleteLater()  # 然后安全删除C++对象
    # ... 调度逻辑 ...
```

**优势：**
- 从字典移除 → 删除C++对象，顺序明确
- `_prune_hq_threads` 不会看到已移除的线程
- 不依赖Qt的信号槽执行顺序

### 修复2：防御性检查

**改动位置：** `_prune_hq_threads()`

新增 `_is_qobject_alive()` 方法：
```python
def _is_qobject_alive(self, obj) -> bool:
    """检查Qt C++对象是否仍然有效"""
    if obj is None:
        return False
    try:
        _ = obj.objectName()  # 无副作用的属性访问
        return True
    except (RuntimeError, AttributeError):
        return False  # C++对象已删除或不是QObject
```

增强 `_prune_hq_threads()`：
```python
def _prune_hq_threads(self, request_stop: bool = False) -> None:
    for token, (thread, worker) in list(self._hq_threads.items()):
        # ✅ 防御性检查：C++对象可能已被删除
        if not self._is_qobject_alive(thread) or not self._is_qobject_alive(worker):
            _debug.log_warning("Found deleted C++ QObject...")
            self._hq_threads.pop(token, None)
            continue
        # ... 现有逻辑 ...
```

**优势：**
- 即使修复1失效，这个防御层也能阻止崩溃
- 自动清理失效的条目
- 记录异常情况便于监控

## 测试验证

**通过的测试：**
- ✅ `test_viewer_coalesces_rapid_load_requests_to_latest_image`
- ✅ `test_viewer_does_not_schedule_old_image_hq_while_new_image_loads`
- ✅ `test_classify_returns_before_slow_move_finishes`
- ✅ `test_viewer_abort_hq_tolerates_deleted_thread_wrappers`
- ✅ `test_hq_worker_cancellation_after_resize_avoids_current_qthread`
- ✅ `test_hq_worker_cancellation_does_not_wrap_current_qthread`
- ✅ `test_viewer_abort_hq_cancels_the_active_worker`

## 修复的鲁棒性

### ✅ 根本性解决
- 不是打补丁，而是改变了生命周期管理策略
- 从「依赖Qt自动管理」变为「显式控制」

### ✅ 多重防护
- 修复1：显式生命周期管理（主要防线）
- 修复2：防御性检查（兜底防线）

### ✅ 不会引入新问题
- 保持原有行为（从字典移除 → 删除对象）
- 只是改变了执行顺序和控制方式
- 所有现有测试通过

### ✅ 向后兼容
- 不改变外部接口
- 不影响其他代码路径

## 预期效果

**修复前：**
- 快速切换+分类操作时偶发崩溃
- 崩溃无日志，难以定位
- Keep Zoom模式下更容易触发

**修复后：**
- 竞争窗口被消除
- 即使出现异常情况，防御性检查也能兜底
- 调试日志记录所有清理动作

## 建议测试

请再次尝试重现崩溃：
1. 启动应用（已启用调试日志）
2. 打开 Keep Zoom 模式
3. 快速滚轮切换图片
4. 频繁按分类键
5. 混合操作：切换→分类→切换（尽可能快）

如果仍然崩溃，`viewer_debug.log` 会记录崩溃前的详细操作序列。
