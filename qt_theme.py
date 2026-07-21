APP_STYLESHEET = """
QMainWindow {
    background: #171a1f;
    color: #e6e8ec;
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 13px;
}

QWidget {
    color: #e6e8ec;
}

QFrame#TopBar {
    background: #1d2128;
    border-bottom: 1px solid #303741;
}

QFrame#ViewerToolbar {
    background: #161a20;
    border-bottom: 1px solid #2b313a;
}

QFrame#ProfilePanel {
    background: #1a1f26;
    border: 1px solid #303741;
    border-radius: 6px;
    padding: 10px;
}

QFrame#SidePanel,
QFrame#InspectorPanel {
    background: #20242b;
    border: 1px solid #303741;
}

QFrame#ViewerSurface {
    background: #111419;
    border: 1px solid #2b313a;
}

QFrame#DialogHeader {
    background: transparent;
}

QFrame#DialogFormPanel {
    background: #171b22;
    border: 1px solid #303741;
    border-radius: 7px;
}

QLabel#PanelTitle {
    color: #f3f5f7;
    font-size: 14px;
    font-weight: 650;
}

QLabel#SectionLabel {
    color: #9ca6b4;
    font-size: 12px;
    font-weight: 600;
}

QLabel#MutedText,
QLabel#PathLabel,
QLabel#MetricLabel {
    color: #9ca6b4;
}

QLabel#DialogTitle {
    color: #f3f5f7;
    font-size: 18px;
    font-weight: 700;
}

QLabel#DialogSubtitle,
QLabel#FieldLabel,
QLabel#KeyColumnHeader,
QLabel#FolderColumnHeader {
    color: #9ca6b4;
    font-size: 12px;
    font-weight: 650;
}

QLabel#ViewerTitle {
    color: #f3f5f7;
    font-size: 20px;
    font-weight: 650;
}

QLabel#KeyCap {
    background: #15191f;
    border: 1px solid #3a4350;
    border-radius: 5px;
    color: #d7dde6;
    font-size: 12px;
    font-weight: 700;
    padding: 3px 7px;
}

QPushButton {
    background: #2b313a;
    border: 1px solid #3a4350;
    border-radius: 6px;
    padding: 6px 10px;
    color: #e6e8ec;
}

QPushButton:hover {
    background: #343c47;
}

QPushButton:pressed,
QPushButton:checked {
    background: #1f6f68;
    border-color: #2a9d8f;
}

QPushButton#PrimaryButton {
    background: #1f7a70;
    border-color: #2a9d8f;
    font-weight: 650;
}

QPushButton#ClassifyButton {
    text-align: left;
    padding: 8px 10px;
    min-height: 22px;
    background: #252b34;
}

QPushButton#SubtleButton {
    background: #222832;
    border-color: #343c47;
}

QCheckBox#LinkSwitch {
    spacing: 5px;
    color: #c4ccd7;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.2px;
    background: transparent;
    border: none;
    padding: 0;
    margin: 0;
    min-height: 18px;
    max-height: 20px;
}

QCheckBox#LinkSwitch:hover {
    color: #edf1f5;
}

QCheckBox#LinkSwitch:checked {
    color: #9fe3da;
}

QCheckBox#LinkSwitch:disabled {
    color: #6d7683;
}

QCheckBox#LinkSwitch::indicator {
    width: 28px;
    height: 15px;
    border-radius: 8px;
    border: 1px solid #3a4350;
    background: #2b313a;
}

QCheckBox#LinkSwitch::indicator:hover {
    border-color: #566173;
    background: #343c47;
}

QCheckBox#LinkSwitch::indicator:checked {
    background: #1f6f68;
    border-color: #2a9d8f;
}

QCheckBox#LinkSwitch::indicator:checked:hover {
    background: #24877e;
    border-color: #34b5a5;
}

QCheckBox#LinkSwitch::indicator:disabled {
    background: #1a1f26;
    border-color: #303741;
}

QComboBox#ColumnCombo {
    min-width: 64px;
    max-width: 78px;
    padding: 3px 6px;
    background: #222832;
    border: 1px solid #343c47;
}

QPushButton#AddMappingButton {
    background: #1f3d3d;
    border-color: #2d6f69;
    color: #dff6f2;
    font-weight: 650;
    padding: 7px 12px;
}

QPushButton#AddMappingButton:hover {
    background: #24514f;
    border-color: #2a9d8f;
}

QPushButton#SortMappingButton {
    background: #243040;
    border-color: #3a4d63;
    color: #d7e6f5;
    font-weight: 650;
    padding: 7px 12px;
}

QPushButton#SortMappingButton:hover {
    background: #2c3c50;
    border-color: #4f7396;
}

QPushButton#DeleteMappingButton {
    background: #2a2426;
    border-color: #574049;
    color: #e3b7c0;
    padding: 6px 9px;
}

QPushButton#DeleteMappingButton:hover {
    background: #3a2a2f;
    border-color: #875160;
    color: #f0c9d1;
}

QDialog {
    background: #1b2027;
    color: #e6e8ec;
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 13px;
}

QDialog#WorkbenchDialog {
    background: #1b2027;
}

QMessageBox {
    background: #1b2027;
    color: #e6e8ec;
}

QLineEdit,
QAbstractSpinBox {
    background: #12161c;
    border: 1px solid #3a4350;
    border-radius: 6px;
    color: #edf1f5;
    selection-background-color: #1f6f68;
    selection-color: #f3f7f8;
    padding: 6px 9px;
}

QLineEdit:hover,
QAbstractSpinBox:hover {
    border-color: #566173;
}

QLineEdit:focus,
QAbstractSpinBox:focus {
    border-color: #2a9d8f;
    background: #151a21;
}

QLineEdit:disabled,
QAbstractSpinBox:disabled {
    color: #6f7784;
    background: #171b21;
    border-color: #2a3038;
}

QSpinBox {
    min-height: 28px;
}

QSpinBox::up-button,
QSpinBox::down-button {
    background: #202732;
    border-left: 1px solid #303741;
    width: 18px;
}

QSpinBox::up-button:hover,
QSpinBox::down-button:hover {
    background: #2a333f;
}

QDialogButtonBox QPushButton {
    min-width: 82px;
    padding: 7px 13px;
}

QComboBox {
    background: #15191f;
    border: 1px solid #3a4350;
    border-radius: 6px;
    padding: 5px 9px;
    min-width: 120px;
}

QComboBox:hover {
    border-color: #566173;
}

QComboBox QAbstractItemView {
    background: #20242b;
    border: 1px solid #3a4350;
    selection-background-color: #1f6f68;
}

QListWidget {
    background: #171b21;
    border: 1px solid #303741;
    border-radius: 6px;
    padding: 4px;
    outline: none;
}

QListWidget::item {
    border-radius: 5px;
    padding: 7px 8px;
}

QListWidget#KeyBindingsList::item {
    padding: 0;
}

QListWidget::item:selected {
    background: #1f6f68;
}

QListWidget#KeyBindingsList::item:selected {
    background: #26323a;
    border: 1px solid #3f5b63;
    color: #edf1f5;
}

QSplitter::handle {
    background: #171a1f;
}

QStatusBar {
    background: #15191f;
    border-top: 1px solid #303741;
    color: #b8c0cc;
}
"""
