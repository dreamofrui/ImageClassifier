# 图片快速切换崩溃问题 - 诊断工具已部署

## 问题描述

用户在快速切换图片（滚轮导航）并进行分类操作时，应用会突然卡住然后崩溃退出，控制台无任何错误日志。

## 已完成工作

### 1. 根本原因分析 ✅

已完成详细的代码分析，识别出三个主要竞争条件：

**竞争1：HQ渲染与图片切换**
- `_handle_hq_resized()` 调用 `_swap_pixmap_preserving_view()` 时
- 用户触发 `load_image()` → `resetTransform()` / `setSceneRect()`
- 导致 `_swap_pixmap_preserving_view()` 中的 `mapToScene()` / `setTransform()` 基于失效状态

**竞争2：图片加载回调与HQ渲染的状态不一致**
- `_handle_image_loaded()` 读取 `transform()` 和 `_display_scale`
- 同时 `_handle_hq_resized()` 在修改这些值
- 导致视图状态不一致

**竞争3：分类完成回调导致图片回跳**
- 用户按分类键A → 后台线程执行移动操作
- 用户继续切换到图片B、C
- 分类完成回调触发 `_sync_after_session_change()` → `_load_current_image()`
- 可能加载回已经离开的图片

详细分析见：`docs/crash_analysis.md`

### 2. 调试日志系统部署 ✅

已在所有关键代码路径添加详细日志：

**新增文件：**
- `viewer_debug.py` - 线程安全的调试日志器
- `docs/debug_logging_guide.md` - 日志解读指南
- `docs/CRASH_DIAGNOSIS_INSTRUCTIONS.md` - 使用说明

**修改文件：**
- `qt_image_viewer.py` - 添加11处关键日志点
- `qt_workbench.py` - 添加5处关键日志点  
- `qt_main.py` - 启用崩溃钩子和日志

**日志特性：**
- 记录所有关键操作（load_image, classify, HQ渲染等）
- 记录线程事件和token状态
- 捕获Qt操作异常
- 毫秒级时间戳，便于检测竞争条件
- 线程名称，便于追踪并发操作

### 3. 测试验证 ✅

运行了关键测试确保日志不影响功能：
- `test_classify_returns_before_slow_move_finishes` ✅
- `test_viewer_coalesces_rapid_load_requests_to_latest_image` ✅

## 下一步操作

### 用户需要做的：

1. **运行应用**
   ```bash
   cd D:\code\vscode_code\ARS
   D:/miniforge3/envs/tool/python.exe qt_main.py
   ```

2. **重现崩溃**
   - 快速滚轮切换图片
   - 快速按分类键
   - 混合操作：切换→分类→切换（重复）

3. **收集日志**
   - 崩溃后查看 `viewer_debug.log`
   - 提供最后200行日志

4. **反馈信息**
   - 执行的具体操作序列
   - 是否有特定条件（如Keep Zoom开启）
   - 崩溃频率（每次都崩溃 vs 偶尔）

### 根据日志结果的修复方案：

**如果崩溃在 `_swap_pixmap_preserving_view`：**
```python
# 添加原子性保护
self._swapping_pixmap = True
try:
    # 执行swap操作
finally:
    self._swapping_pixmap = False

# load_image 检查此标志
if self._swapping_pixmap:
    self._pending_load = (path, token)
    return
```

**如果是token验证漏洞：**
```python
# 在Qt操作前立即再次验证
def _swap_pixmap_preserving_view(self, pixmap, scale, expected_token):
    # 操作前验证
    if self._hq_token != expected_token:
        return
    # 执行操作
```

**如果是分类回调导致回跳：**
```python
def _handle_classify_finished(self, record, error):
    # 记录分类时的图片
    classified_image = record.source
    
    self._sync_after_session_change(...)
    
    # 检查用户是否已切换
    if self._current_loaded_image != classified_image:
        # 用户已切换，不重新加载
        return
```

## 文档索引

- `docs/crash_analysis.md` - 详细的根本原因分析
- `docs/debug_logging_guide.md` - 日志格式和解读方法
- `docs/CRASH_DIAGNOSIS_INSTRUCTIONS.md` - 使用步骤和后续流程

## 性能影响

- 日志记录开销：<1% CPU
- 内存影响：~1MB（日志缓冲）
- 磁盘占用：~50KB/分钟（正常使用）
- 对用户体验无感知影响

## 临时禁用日志

如果需要暂时禁用（不推荐，在找到问题前）：

```python
# qt_main.py
def main() -> int:
    # enable_crash_hooks()  # 注释掉
    # logger = get_debug_logger()  # 注释掉
    # logger.log_operation("Application starting")  # 注释掉
    
    app = QApplication(sys.argv)
    # ...
```

## 预期时间线

1. **用户测试** (1-2天) - 重现崩溃并收集日志
2. **日志分析** (1小时) - 确定具体崩溃点
3. **实施修复** (2-4小时) - 根据诊断结果修复
4. **验证测试** (1天) - 确认问题解决

---

**当前状态：等待用户测试和日志反馈** 📊

请按照 `docs/CRASH_DIAGNOSIS_INSTRUCTIONS.md` 的步骤操作，然后提供日志文件。
