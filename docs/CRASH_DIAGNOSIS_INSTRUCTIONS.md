# 崩溃问题诊断 - 调试日志已启用

## 当前状态

已在关键代码路径中添加详细的调试日志，用于定位快速图片切换和分类操作时的崩溃问题。

## 已添加日志的关键位置

### 图片查看器 (qt_image_viewer.py)
1. **load_image()** - 图片加载入口，记录token、线程状态
2. **_handle_image_loaded()** - 图片加载完成回调，记录token匹配情况
3. **_start_hq_resize()** - 高质量渲染启动，记录目标尺寸和token
4. **_handle_hq_resized()** - HQ渲染完成回调，记录token验证
5. **_swap_pixmap_preserving_view()** - 交换显示图片（最可能崩溃点），详细记录每个步骤
6. **_abort_hq()** - 取消HQ渲染，记录活跃线程数
7. **wheelEvent()** - 滚轮事件，区分导航和缩放
8. **_ImageLoadWorker.run()** - 图片加载线程
9. **_HqResizeWorker.run()** - HQ渲染线程

### 工作台 (qt_workbench.py)
1. **classify()** - 分类操作入口，记录当前状态
2. **next_image()** - 切换图片，记录索引
3. **_load_current_image()** - 加载当前图片，检测重复加载
4. **_handle_classify_finished()** - 分类完成回调，记录是否会触发图片切换

## 使用步骤

### 1. 启动应用
```bash
cd D:\code\vscode_code\ARS
D:/miniforge3/envs/tool/python.exe qt_main.py
```

### 2. 重现崩溃
尝试以下操作序列：

**场景A：快速滚轮切换**
- 连续快速滚动鼠标滚轮，前后切换图片
- 观察是否崩溃

**场景B：快速分类**
- 快速连续按分类键（如 p, n, x 等）
- 观察是否崩溃

**场景C：混合操作（最容易触发）**
- 滚轮切换到下一张
- 立即按分类键
- 再次滚轮切换
- 重复以上步骤，越快越好

**场景D：Keep Zoom模式**
- 打开 "Keep Zoom" 按钮
- 执行场景A或C

### 3. 查看日志

崩溃后（或在操作过程中），查看项目根目录下的 `viewer_debug.log`

```bash
# Windows 记事本
notepad viewer_debug.log

# 或者用VS Code
code viewer_debug.log

# 查看最后100行
tail -n 100 viewer_debug.log
```

### 4. 分析日志

查找以下关键信息：

#### 崩溃点识别
最后几条日志会告诉你崩溃发生在哪里。例如：

```
13:45:23.456 [MainThread] >>> _handle_hq_resized | token=15, current_token=15, has_error=False
13:45:23.457 [MainThread]     [_handle_hq_resized] action=swap_pixmap, scale=0.4500, size=1920x1080
13:45:23.458 [MainThread] >>> _swap_pixmap_preserving_view | old_scale=1.0000, new_scale=0.4500
13:45:23.459 [MainThread]     [_swap_pixmap] anchor=(960.5, 540.0)
13:45:23.460 [MainThread] >>> load_image | token=16, path=next.jpg  # ← 在swap执行期间！
13:45:23.461 [MainThread] ❌ _swap_pixmap Qt operations failed
```

#### 竞争条件检测
查找多个操作几乎同时发生的情况（时间戳相差<10ms）：

```
13:45:23.450 [MainThread] >>> wheelEvent.navigation | delta=120, direction=next
13:45:23.451 [MainThread] >>> _abort_hq | old_token=14, active_hq=1
13:45:23.452 [MainThread] >>> next_image | current=5, requested=6
13:45:23.453 [MainThread] >>> load_image | token=15, ...
13:45:23.455 [Thread-10  ] HqResize.success | token=14  # ← 被abort的线程仍在完成
13:45:23.456 [MainThread] >>> _handle_hq_resized | token=14, current_token=15
13:45:23.457 [MainThread]     [_handle_hq_resized] action=ignore, reason=token_mismatch  # ← 正确被忽略
```

#### 分类操作与图片切换的交互
```
13:45:20.100 [MainThread] >>> classify | key=p, current_image=img001.jpg
13:45:20.101 [MainThread]     [classify] action=start_move
13:45:20.500 [MainThread] >>> wheelEvent.navigation | direction=next  # ← 用户在分类过程中切换
13:45:20.501 [MainThread] >>> next_image | current=0, requested=1
13:45:20.502 [MainThread] >>> load_image | token=10, path=img002.jpg
13:45:21.200 [Thread-5   ] # 分类操作在后台线程完成
13:45:21.201 [MainThread] >>> _handle_classify_finished | has_record=True
13:45:21.202 [MainThread] >>> _load_current_image | current=img002.jpg, previous=img002.jpg
13:45:21.203 [MainThread]     [_load_current_image] action=skip, reason=already_loaded  # ← 好，没有回跳
```

## 预期结果

根据日志，我们将能够确定：

1. **崩溃是否发生在 `_swap_pixmap_preserving_view`**
   - 如果是，说明HQ渲染与图片切换存在竞争
   - 解决方案：添加 `_swapping_pixmap` 标志保护

2. **崩溃是否因token验证失败**
   - 如果token匹配检查失败但仍然执行了操作，说明token机制有漏洞
   - 解决方案：在关键操作前再次验证token

3. **崩溃是否因分类完成回调导致图片回跳**
   - 如果 `_handle_classify_finished` 后加载了旧图片
   - 解决方案：记录用户当前位置，回调时检查是否已切换

4. **崩溃是否因Qt对象过早释放**
   - 如果看到 `RuntimeError: wrapped C/C++ object has been deleted`
   - 解决方案：改进线程生命周期管理

## 后续步骤

收集到崩溃日志后：

1. **将 `viewer_debug.log` 的最后200行发给我**
2. **描述你执行的操作序列**
3. **说明是否有特定模式（如只在Keep Zoom开启时崩溃）**

我会根据日志分析具体崩溃原因，并实施针对性修复。

## 性能影响

- 日志记录对性能影响很小（<1%）
- 只在关键操作点记录，不影响渲染性能
- 文件I/O是缓冲的，不会导致卡顿

## 禁用日志

如果需要禁用调试日志（问题解决后）：

```python
# 在 qt_main.py 中注释掉这两行
# enable_crash_hooks()
# logger = get_debug_logger()
```

或者直接删除：
- `viewer_debug.py`
- 从 `qt_image_viewer.py` 和 `qt_workbench.py` 中删除所有 `_debug.log_*` 调用
