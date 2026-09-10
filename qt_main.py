import sys

from PySide6.QtWidgets import QApplication

from config_manager import ConfigManager
from qt_workbench import AnnotationWorkbench
from viewer_debug import (
    enable_crash_hooks,
    get_debug_logger,
    install_qt_message_handler,
)


def main() -> int:
    # Enable debug logging for crash diagnosis (ARS_VIEWER_DEBUG=1 to enable)
    enable_crash_hooks()
    logger = get_debug_logger()
    logger.log_operation("Application starting")

    app = QApplication(sys.argv)
    install_qt_message_handler()
    config_manager = ConfigManager()
    window = AnnotationWorkbench(config_manager)
    window.show()

    logger.log_operation("Application window shown, entering event loop")
    result = app.exec()

    logger.log_operation("Application exiting", exit_code=result)
    logger.flush()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
