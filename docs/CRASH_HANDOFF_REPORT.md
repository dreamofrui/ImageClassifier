# 崩溃问题诊断进展报告

## 执行时间线
- 2026-09-09 上午：初次定位并实施修复
- 2026-09-09 10:49：用户测试2分钟后再次崩溃

---

## 第一次崩溃分析（已完成）

### 崩溃现象
- 位置：`_abort_hq()` → `_prune_hq_threads()` 
- 日志：`10:26:55.035 [MainThread] >>> _abort_hq | old_token=1953, active_hq=1`（然后中断）
- 原因：访问已被 `deleteLater()` 标记删除的C++ QThread对象

### 第一次修复方案
**实施内容：**
1. 显式生命周期管理：移除 `thread.finished.connect(thread.deleteLater)`，改为：
   ```python
   thread.finished.connect(lambda: self._cleanup_hq_thread(token))
   ```
2. 防御性检查：`_is_qobject_alive()` + 增强的 `_prune_hq_threads()`
3. 新增 `_cleanup_hq_thread(token)` 方法

**测试结果：** ✅ 13/13 测试全部通过

---

## 第二次崩溃分析（当前问题）

### 崩溃现象
```
10:49:24.956 [Dummy-44] HqResize.cancelled_late | token=121
10:49:24.956 [Dummy-45] ImageLoad.success | token=40
10:49:24.966 [MainThread] _handle_hq_resized | token=121, current_token=122 (ignored)
10:49:24.966 [MainThread] _handle_image_loaded | token=40
10:49:24.966 [MainThread] >>> _abort_hq | old_token=122, active_hq=1
[崩溃 - 无后续日志]
```

### 关键发现
**没有看到 `_cleanup_hq_thread token=121` 的日志！**

这说明 `thread.finished` 信号的lambda回调**没有被触发**。

### 根本问题

**时序问题：**
```
1. HQ线程121完成resize
2. worker.finished 信号发射
3. worker.finished → thread.quit()  (line 695)
4. worker.finished → _handle_hq_resized() (token不匹配，被忽略)
5. 图片加载完成 → _handle_image_loaded(token=40)
6. _handle_image_loaded → _abort_hq()
7. _abort_hq → _prune_hq_threads() 
8. 此时 thread.quit() 已调用，但 thread.finished 还没触发
9. _prune_hq_threads 看到 _hq_threads[121] 还在
10. 尝试访问 thread/worker → 崩溃
```

**根本原因：**
- `thread.quit()` 是异步的，只是请求退出
- `thread.finished` 信号在线程真正结束后才触发
- 在这个窗口期，字典中的条目还在，但对象可能已经在清理中
- `_cleanup_hq_thread()` 依赖 `thread.finished`，但它触发太晚了

### 第一次修复的缺陷
我们把清理时机绑定到 `thread.finished`，但应该绑定到 `worker.finished`：
- `worker.finished` → 工作完成（可以立即清理）
- `thread.finished` → 线程退出（太晚了，已经有竞争窗口）

---

## 正确的修复方案

### 方案A：在 worker.finished 时立即清理（推荐）

```python
def _start_hq_resize(self) -> None:
    # ... 现有代码 ...
    
    thread = QThread(self)
    worker = _HqResizeWorker(token, source_copy, target_w, target_h, src_w)
    worker.moveToThread(thread)
    
    thread.started.connect(worker.run)
    
    # ✅ 关键：在 worker.finished 时立即清理字典
    worker.finished.connect(
        lambda t=token: self._cleanup_hq_thread_early(t)
    )
    
    worker.finished.connect(self._handle_hq_resized)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    
    # thread.finished 只负责 deleteLater
    thread.finished.connect(thread.deleteLater)
    
    self._hq_threads[token] = (thread, worker)
    thread.start()

def _cleanup_hq_thread_early(self, token: int) -> None:
    """在worker完成时立即从字典移除，防止竞争访问"""
    _debug.log_operation("_cleanup_hq_thread_early", token=token)
    
    # 立即从字典移除
    entry = self._hq_threads.pop(token, None)
    if entry is None:
        return
    
    # 检查是否需要调度下一个HQ任务
    if token == self._hq_token or self._hq_threads:
        return
    if self._has_image and self._loading_path is None:
        self._schedule_hq_settle()
```

**原理：**
- `worker.finished` 发射后立即清理字典
- `_prune_hq_threads` 不会看到这个条目
- 消除竞争窗口

### 方案B：改进 _prune_hq_threads 的检查逻辑

在 `_is_qobject_alive()` 中增加更严格的检查：

```python
def _is_qobject_alive(self, obj) -> bool:
    """检查Qt C++对象是否仍然有效"""
    if obj is None:
        return False
    try:
        # 检查多个属性
        _ = obj.objectName()
        # 对于QThread，额外检查 isFinished
        if isinstance(obj, QThread):
            _ = obj.isFinished()  # 可能触发RuntimeError
        return True
    except (RuntimeError, AttributeError):
        return False
```

**但这仍然不够，因为在 `isFinished()` 和后续访问之间仍有窗口。**

---

## 推荐的完整解决方案

**组合方案A + 保留防御性检查：**

1. **主要修复：** 在 `worker.finished` 时立即清理字典（方案A）
2. **保留防御：** `_is_qobject_alive()` 和增强的 `_prune_hq_threads()`
3. **移除：** `thread.finished` 的清理逻辑（已经在worker.finished中处理）

---

## 代码修改清单

### 需要修改的文件
1. `qt_image_viewer.py`
   - 修改 `_start_hq_resize()` - 将清理绑定到 `worker.finished`
   - 重命名 `_cleanup_hq_thread()` → `_cleanup_hq_thread_early()`
   - 简化逻辑：移除 thread.finished 的lambda

### 测试验证
- 运行所有HQ测试
- 手动测试：快速切换+分类操作

---

## 调试信息收集

### 当前日志显示的问题
```
10:49:24.956 [Dummy-44] HqResize.cancelled_late | token=121
10:49:24.966 [MainThread] _handle_hq_resized | token=121 (ignored)
10:49:24.966 [MainThread] _abort_hq | old_token=122, active_hq=1
```

**缺失的日志：**
- `_cleanup_hq_thread token=121` - 说明 thread.finished 没触发

**需要添加的日志：**
- 在 `worker.finished` 的所有连接点添加日志
- 在 `thread.quit()` 调用后添加日志

---

## 根本问题总结

### 信号时序问题
Qt的信号连接顺序很重要：
```python
worker.finished.connect(A)  # 第1个
worker.finished.connect(B)  # 第2个
worker.finished.connect(C)  # 第3个
```
按连接顺序依次触发：A → B → C

**当前错误的顺序：**
```python
worker.finished.connect(self._handle_hq_resized)  # 1
worker.finished.connect(thread.quit)              # 2
worker.finished.connect(worker.deleteLater)       # 3
thread.finished.connect(_cleanup_hq_thread)       # 等thread退出后
```

**正确的顺序：**
```python
worker.finished.connect(_cleanup_hq_thread_early) # 1 - 立即清理字典
worker.finished.connect(self._handle_hq_resized)  # 2
worker.finished.connect(thread.quit)              # 3
worker.finished.connect(worker.deleteLater)       # 4
thread.finished.connect(thread.deleteLater)       # 线程退出后清理C++对象
```

---

## 下一步行动

### 立即执行
1. 实施方案A（在worker.finished时清理）
2. 添加额外的调试日志验证修复
3. 运行测试套件

### 验证步骤
1. 运行所有HQ测试
2. 手动测试快速操作
3. 查看日志确认 `_cleanup_hq_thread_early` 被正确调用
4. 确认不再有 `active_hq > 0` 时的崩溃

### 如果还是崩溃
- 检查是否在 `worker.finished` 的其他回调中也需要类似修复
- 考虑完全移除字典，改用其他跟踪机制
- 记录完整的信号触发序列

---

## 技术教训

1. **不要依赖 thread.finished 做及时清理** - 它触发太晚
2. **字典清理要在工作完成时立即进行** - 不要等线程退出
3. **信号连接顺序很重要** - 清理应该是第一个连接
4. **防御性检查是必要的** - 但不能替代正确的时序

---

## 文档索引

- `docs/CRASH_ROOT_CAUSE.md` - 第一次崩溃的根因分析
- `docs/FIX_COMPLETE.md` - 第一次修复的完整文档
- `docs/debug_logging_guide.md` - 调试日志使用指南
- 本文档 - 第二次崩溃的分析和解决方案

---

**报告时间：** 2026-09-09 10:55
**状态：** 第二次崩溃已定位根因，修复方案已明确，待实施
**下一步：** 实施方案A并验证
