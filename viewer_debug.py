"""
调试日志工具 - 用于定位图片查看器崩溃问题
"""
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path


class ViewerDebugLogger:
    """线程安全的调试日志记录器"""

    def __init__(self, log_file: Path | None = None):
        if log_file is None:
            log_file = Path("viewer_debug.log")

        self.log_file = log_file
        self.logger = logging.getLogger("ViewerDebug")
        self.logger.setLevel(logging.DEBUG)

        # 文件处理器 - 详细日志
        fh = logging.FileHandler(log_file, mode='w', encoding='utf-8')
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
        self.logger.warning(f"⚠️  {message} | {ctx_str}")

    def log_error(self, message: str, exc: Exception | None = None):
        """记录错误"""
        self.logger.error(f"❌ {message}")
        if exc:
            self.logger.error(f"   Exception: {type(exc).__name__}: {exc}")
            self.logger.error("   Traceback:")
            for line in traceback.format_tb(exc.__traceback__):
                self.logger.error(f"   {line.rstrip()}")

    def log_critical(self, message: str, **context):
        """记录严重问题"""
        ctx_str = ", ".join(f"{k}={v}" for k, v in context.items())
        self.logger.critical(f"🔥 CRITICAL: {message} | {ctx_str}")

    def flush(self):
        """强制刷新日志到磁盘"""
        for handler in self.logger.handlers:
            handler.flush()


# 全局单例
_debug_logger = None


def get_debug_logger() -> ViewerDebugLogger:
    """获取全局调试日志器"""
    global _debug_logger
    if _debug_logger is None:
        _debug_logger = ViewerDebugLogger()
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
        logger.logger.error("Full traceback:")
        for line in traceback.format_tb(exc_traceback):
            logger.logger.error(f"  {line.rstrip()}")
        logger.flush()
        # 调用原始处理器
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = exception_hook
    logger.log_operation("Crash hooks enabled")
