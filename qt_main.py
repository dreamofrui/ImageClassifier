import sys

from PySide6.QtWidgets import QApplication

from config_manager import ConfigManager
from qt_workbench import AnnotationWorkbench


def main() -> int:
    app = QApplication(sys.argv)
    config_manager = ConfigManager()
    window = AnnotationWorkbench(config_manager)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
