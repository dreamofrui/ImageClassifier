"""
调试日志工具 - 用于定位图片查看器崩溃问题

默认关闭（零开销）；设置环境变量 ARS_VIEWER_DEBUG=1 开启。
日志路径可用 ARS_VIEWER_DEBUG_LOG 覆盖，默认 viewer_debug.log（2MB 轮转）。
"""
import logging
import os
import sys
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 环境变量名
_DEBUG_ENV = "ARS_VIEWER_DEBUG"
_LOG_PATH_ENV = "ARS_VIEWER_DEBUG_LOG"
# 单文件上限 2MB，保留 1 个备份
_MAX_BYTES = 2_000_000
_BACKUP_COUNT = 1


class ViewerDebugLogger:
    """线程安全的调试日志记录器"""

    def __init__(self, log_file: Path | None = None):
        if log_file is None:
            log_file = Path(os.environ.get(_LOG_PATH_ENV, "viewer_debug.log"))

        self.log_file = log_file
        self.logger = logging.getLogger("ViewerDebug")
        self.logger.setLevel(logging.DEBUG)

        # 文件处理器 - 详细日志（追加 + 轮转，避免每次启动截断历史）
        fh = RotatingFileHandler(
            log_file,
            mode="a",
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            '%(asctime)s.%(msecs)03d [%(threadName)-10s] %(levelname)-8s %(message)s',
            datefmt='%H:%M:%S'
        ))

        # 控制台处理器 - 只显示关键信息
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.WARNING)
        ch.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))

        self.logger.addHandler(fh)
        self.logger.addHandler(ch)

        self.logger.info("=" * 80)
        self.logger.info(f"Viewer Debug Logger initialized - {datetime.now()}")
        self.logger.info("=" * 80)

    def log_operation(self, operation: str, **context):
        """记录操作及上下文"""
        ctx_str = ", ".join(f"{k}={v}" for k, v in context.items())
        self.logger.debug(f">>> {operation} | {ctx_str}")

    def log_state(self, component: str, **state):
        """记录组件状态"""
        state_str = ", ".join(f"{k}={v}" for k, v in state.items())
        self.logger.debug(f"    [{component}] {state_str}")

    def log_thread_event(self, event: str, thread_id, **context):
        """记录线程事件"""
        ctx_str = ", ".join(f"{k}={v}" for k, v in context.items())
        self.logger.debug(f"    [Thread-{thread_id}] {event} | {ctx_str}")

    def log_warning(self, message: str, **context):
        """记录警告"""
        ctx_str = ", ".join(f"{k}={v}" for k, v in context.items()) if context else ""
        self.logger.warning(f"[WARN] {message} | {ctx_str}")

    def log_error(self, message: str, exc: Exception | None = None):
        """记录错误"""
        self.logger.error(f"[ERROR] {message}")
        if exc:
            self.logger.error(f"   Exception: {type(exc).__name__}: {exc}")
            self.logger.error("   Traceback:")
            for line in traceback.format_tb(exc.__traceback__):
                self.logger.error(f"   {line.rstrip()}")

    def log_critical(self, message: str, **context):
        """记录严重问题"""
        ctx_str = ", ".join(f"{k}={v}" for k, v in context.items())
        self.logger.critical(f"[CRITICAL] {message} | {ctx_str}")

    def flush(self):
        """强制刷新日志到磁盘"""
        for handler in self.logger.handlers:
            handler.flush()


class _DisabledLogger:
    """关闭状态下的空实现 - 与 ViewerDebugLogger 相同方法面，零文件 I/O"""

    def __init__(self):
        self.logger = logging.getLogger("ViewerDebug.Disabled")
        self.logger.addHandler(logging.NullHandler())
        self.logger.propagate = False
        self.log_file = None

    def log_operation(self, operation: str, **context):
        pass

    def log_state(self, component: str, **state):
        pass

    def log_thread_event(self, event: str, thread_id, **context):
        pass

    def log_warning(self, message: str, **context):
        pass

    def log_error(self, message: str, exc: Exception | None = None):
        pass

    def log_critical(self, message: str, **context):
        pass

    def flush(self):
        pass


# 全局单例
_debug_logger = None


def _debug_enabled() -> bool:
    return os.environ.get(_DEBUG_ENV, "").strip().lower() in ("1", "true", "yes")


def get_debug_logger() -> ViewerDebugLogger | _DisabledLogger:
    """获取全局调试日志器（ARS_VIEWER_DEBUG 开启时写文件，否则为空实现）"""
    global _debug_logger
    if _debug_logger is None:
        if _debug_enabled():
            _debug_logger = ViewerDebugLogger()
        else:
            _debug_logger = _DisabledLogger()
    return _debug_logger


def enable_crash_hooks():
    """启用崩溃钩子捕获未处理异常"""
    logger = get_debug_logger()

    def exception_hook(exc_type, exc_value, exc_traceback):
        logger.log_critical(
            "Unhandled exception",
            type=exc_type.__name__,
            value=str(exc_value)
        )
        if isinstance(logger, ViewerDebugLogger):
            logger.logger.error("Full traceback:")
            for line in traceback.format_tb(exc_traceback):
                logger.logger.error(f"  {line.rstrip()}")
        logger.flush()
        # 调用原始处理器
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = exception_hook
    logger.log_operation("Crash hooks enabled")


def install_qt_message_handler():
    """
    安装 Qt 消息处理器，把 Qt 层警告/错误路由进调试日志。

    这是捕获 "QThread: Destroyed while thread is still running"、跨线程
    parenting 警告等 Qt C++ 层消息的唯一可靠通道 —— sys.excepthook
    看不到它们。
    """
    logger = get_debug_logger()

    def message_handler(msg_type, context, message):
        level_map = {
            0: logger.log_warning,   # QtDebugMsg (默认不记，降级为 warning 级)
            1: logger.log_warning,   # QtWarningMsg
            2: logger.log_error,     # QtCriticalMsg
            3: logger.log_critical,  # QtFatalMsg
            4: logger.log_warning,   # QtInfoMsg
        }
        handler_fn = level_map.get(int(msg_type), logger.log_warning)
        handler_fn(f"Qt: {message}", category=context.category if context else "")

    from PySide6.QtCore import qInstallMessageHandler
    qInstallMessageHandler(message_handler)
    logger.log_operation("Qt message handler installed")
