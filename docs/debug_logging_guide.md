# 调试日志使用说明

## 目的
定位图片快速切换和分类操作时的崩溃问题

## 日志文件位置
- 主日志：`viewer_debug.log` (在项目根目录)
- 控制台：只显示WARNING及以上级别

## 使用方法

1. **启动应用**
   ```bash
   python qt_main.py
   ```

2. **重现崩溃**
   - 快速滚轮切换图片
   - 频繁点击分类按钮
   - 组合操作：切换 + 分类 + 再切换

3. **查看日志**
   - 崩溃后立即查看 `viewer_debug.log`
   - 查找最后的操作记录
   - 注意关键时间戳和线程信息

## 日志解读

### 关键操作标记
- `>>> load_image` - 开始加载新图片
- `>>> _handle_image_loaded` - 图片加载完成回调
- `>>> _start_hq_resize` - 开始高质量渲染
- `>>> _handle_hq_resized` - HQ渲染完成回调
- `>>> _swap_pixmap_preserving_view` - 交换显示的图片（关键竞争点）
- `>>> classify` - 分类操作
- `>>> _handle_classify_finished` - 分类完成回调
- `>>> next_image` - 切换到下一张图片
- `>>> wheelEvent.navigation` - 滚轮切换图片

### 线程事件
- `[Thread-XX] ImageLoad.start` - 图片加载线程启动
- `[Thread-XX] HqResize.start` - HQ渲染线程启动
- `[Thread-XX] HqResize.cancelled_early/late` - HQ渲染被取消

### 状态信息
- `[component] key=value` - 组件当前状态
- `action=skip, reason=...` - 操作被跳过的原因
- `token=N, current_token=M` - token不匹配检测

### 错误标记
- `⚠️` - 警告：异常但可恢复的情况
- `❌` - 错误：捕获的异常
- `🔥 CRITICAL` - 严重：未捕获的崩溃

## 崩溃定位线索

### 场景1：_swap_pixmap崩溃
```
>>> _handle_hq_resized | token=5, current_token=5, ...
    [_handle_hq_resized] action=swap_pixmap, scale=0.4500
>>> _swap_pixmap_preserving_view | old_scale=1.0000, new_scale=0.4500
    [_swap_pixmap] anchor=(512.5, 384.0)
>>> load_image | token=6, ...  # <- 在swap执行期间被调用
❌ _swap_pixmap Qt operations failed
```
**原因**：HQ渲染完成时开始swap，但在swap执行到一半时，用户切换图片触发load_image

### 场景2：token竞争
```
>>> _start_hq_resize | token=10, target=1920x1080
[Thread-5] HqResize.start | token=10
>>> load_image | token=6, ...  # <- load_token增加，hq_token也增加
>>> _abort_hq | old_token=10, active_hq=1
[Thread-5] HqResize.success | token=10
>>> _handle_hq_resized | token=10, current_token=11  # <- token已不匹配
    [_handle_hq_resized] action=ignore, reason=token_mismatch
```
**原因**：正常的token保护机制工作

### 场景3：分类后图片回跳
```
>>> classify | key=p, ...
    [classify] action=start_move, current_image=img001.jpg
>>> next_image | current=0, requested=1
>>> load_image | token=7, path=img002.jpg
>>> _handle_classify_finished | has_record=True
    [_handle_classify_finished] action=sync_after_session_change
>>> _load_current_image | current=img002.jpg, previous=img002.jpg
    [_load_current_image] action=skip, reason=already_loaded  # <- 正常
```
或
```
>>> _handle_classify_finished | has_record=True
>>> _load_current_image | current=img001.jpg, previous=img002.jpg  # <- 回跳！
    [_load_current_image] action=load, path=img001.jpg
```

## 预期会看到的模式

### 正常HQ渲染流程
```
load_image (token++) → _abort_hq → _handle_image_loaded → 
fit_to_window → _schedule_hq_settle (140ms timer) → 
_start_hq_resize (token++) → [Thread] HqResize → 
_handle_hq_resized (token check) → _swap_pixmap_preserving_view
```

### 快速切换时的取消
```
load_image(img1, token=1) → [Thread-1] loading...
load_image(img2, token=2) → _abort_hq → pending_load=(img2, 2)
[Thread-1] finishes → _handle_load_thread_finished → 
  _start_image_load(img2, token=2)
```

## 收集信息后的下一步

1. 找到崩溃前最后几条日志
2. 确认是否在 `_swap_pixmap_preserving_view` 中
3. 确认是否有并发的 `load_image` 调用
4. 检查token值是否匹配
5. 根据具体崩溃点实施针对性修复
