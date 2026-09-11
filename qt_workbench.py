import subprocess
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QObject, QSignalBlocker, QSize, Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from binding_profiles import DEFAULT_PROFILE_NAME, normalize_binding_profiles
from classifier_core import (
    ClassifierCoreError,
    ClassifierSession,
    KeyNotBoundError,
    MoveRecord,
    NoCurrentImageError,
)
from qt_image_viewer import ImageViewer
from qt_theme import APP_STYLESHEET
from viewer_debug import get_debug_logger

_debug = get_debug_logger()

MIN_CLASSIFICATION_COLUMNS = 1
MAX_CLASSIFICATION_COLUMNS = 4


class ElidedPathLabel(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._full_text = ""
        self.setObjectName("PathLabel")
        self.setMinimumWidth(180)
        self.setMaximumWidth(16777215)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self._refresh_text()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_text()

    def _refresh_text(self) -> None:
        width = max(self.width() - 8, self.minimumWidth())
        display_text = self.fontMetrics().elidedText(
            self._full_text,
            Qt.TextElideMode.ElideMiddle,
            width,
        )
        QLabel.setText(self, display_text)


class _MoveWorker(QObject):
    finished = Signal(object, object)

    def __init__(self, operation, *args):
        super().__init__()
        self._operation = operation
        self._args = args

    @Slot()
    def run(self) -> None:
        try:
            result = self._operation(*self._args)
        except Exception as exc:
            self.finished.emit(None, exc)
        else:
            self.finished.emit(result, None)


class KeyBindingRow(QFrame):
    def __init__(self, key: str = "", folder: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("KeyBindingRow")
        self.setMinimumHeight(34)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        self.drag_handle = QLabel("::", self)
        self.drag_handle.setObjectName("DragHandle")
        self.drag_handle.setToolTip("Drag to reorder")
        self.drag_handle.setFixedWidth(40)
        self.drag_handle.setMinimumHeight(28)
        self.drag_handle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.key_edit = QLineEdit(self)
        self.key_edit.setObjectName("KeyInput")
        self.key_edit.setMaxLength(1)
        self.key_edit.setFixedWidth(76)
        self.key_edit.setMinimumHeight(28)
        self.key_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.key_edit.setText(key)

        self.folder_edit = QLineEdit(self)
        self.folder_edit.setObjectName("FolderInput")
        self.folder_edit.setMinimumHeight(28)
        self.folder_edit.setText(folder)

        self.delete_button = QPushButton("Delete", self)
        self.delete_button.setObjectName("DeleteMappingButton")
        self.delete_button.setFixedWidth(86)
        self.delete_button.setMinimumHeight(28)

        layout.addWidget(self.drag_handle)
        layout.addWidget(self.key_edit)
        layout.addWidget(self.folder_edit, 1)
        layout.addWidget(self.delete_button)


class AnnotationWorkbench(QMainWindow):
    def __init__(self, config_manager):
        super().__init__()
        self.config_manager = config_manager
        self.classifier_config = deepcopy(
            self.config_manager.get_image_classifier_config()
        )
        self.profiles, self.active_profile, migrated, self.profile_warnings = (
            normalize_binding_profiles(self.classifier_config)
        )
        if migrated:
            self._save_classifier_config()
        self.source_folder: Path | None = None
        self.target_folder: Path | None = None
        self._target_manually_selected = False
        self.session: ClassifierSession | None = None
        self.batch_total_count = 0
        self.recent_operations: list[str] = []
        self._shortcuts: list[QShortcut] = []
        self._shortcut_registry: list[tuple[str, str]] = []
        self._folder_launcher = self._launch_folder
        self._move_in_progress = False
        self._move_thread: QThread | None = None
        self._move_worker: _MoveWorker | None = None
        self._queue_signature: tuple[str, ...] = ()
        self._current_loaded_image: Path | None = None
        self._previous_image_paths: list[Path] = []
        self.move_xml_pairs = bool(self.classifier_config.get("move_xml_pairs", False))
        self.classification_columns = self._normalized_classification_columns(
            self.classifier_config.get("classification_columns", 1)
        )

        self.setWindowTitle("ARS Image Annotation Workbench")
        window_size = self.classifier_config.get("window_size", [1280, 820])
        self.resize(int(window_size[0]), int(window_size[1]))
        self.setStyleSheet(APP_STYLESHEET)

        self._build_ui()
        self.image_viewer.clear("No batch loaded\nSelect Source to begin.")
        self._render_classification_buttons()
        self._register_shortcuts()
        self._build_status_bar()
        self._show_profile_warnings()
        self.statusBar().showMessage("Ready")

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_top_bar())

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.queue_panel = self._build_queue_panel()
        self.viewer_panel = self._build_viewer_panel()
        self.inspector_panel = self._build_inspector_panel()
        self.splitter.addWidget(self.queue_panel)
        self.splitter.addWidget(self.viewer_panel)
        self.splitter.addWidget(self.inspector_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([270, 740, 310])
        root_layout.addWidget(self.splitter, 1)

        self.setCentralWidget(root)

    def _build_top_bar(self) -> QFrame:
        self.top_bar = QFrame()
        self.top_bar.setObjectName("TopBar")
        layout = QHBoxLayout(self.top_bar)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        self.source_button = QPushButton("Source")
        self.source_button.setObjectName("PrimaryButton")
        self.source_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        self.source_button.clicked.connect(self.select_source_folder)
        self.source_path_label = self._path_label("No source folder")

        self.target_button = QPushButton("Target")
        self.target_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        )
        self.target_button.clicked.connect(self.select_target_folder)
        self.target_path_label = self._path_label("Default: same as source")

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("SubtleButton")
        self.refresh_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.refresh_button.clicked.connect(self.refresh_batch)

        self.open_folder_button = QPushButton("Open")
        self.open_folder_button.setObjectName("SubtleButton")
        self.open_folder_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirLinkIcon)
        )
        self.open_folder_button.clicked.connect(self.open_current_folder)

        self.presentation_button = QPushButton("Presentation")
        self.presentation_button.setObjectName("SubtleButton")
        self.presentation_button.setCheckable(True)
        self.presentation_button.clicked.connect(self._toggle_presentation_mode)

        layout.addWidget(self.source_button)
        layout.addWidget(self.source_path_label, 2)
        layout.addWidget(self.target_button)
        layout.addWidget(self.target_path_label, 2)
        layout.addStretch(1)
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.open_folder_button)
        layout.addWidget(self.presentation_button)

        return self.top_bar

    def _build_queue_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("SidePanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        header.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        title = QLabel("Queue")
        title.setObjectName("PanelTitle")
        self.queue_count_label = QLabel("0 images")
        self.queue_count_label.setObjectName("MetricLabel")
        self.queue_count_label.setMinimumHeight(34)
        self.queue_count_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.queue_back_button = QPushButton("Back", panel)
        self.queue_back_button.setObjectName("SubtleButton")
        self.queue_back_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack)
        )
        self.queue_back_button.setToolTip("Back to previous image")
        self.queue_back_button.clicked.connect(self.back_to_previous_image)
        self.queue_back_button.setFixedSize(78, 34)
        header.addWidget(title)
        header.addWidget(self.queue_count_label, 1)
        header.addWidget(self.queue_back_button)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.queue_search_input = QLineEdit(panel)
        self.queue_search_input.setObjectName("QueueSearchInput")
        self.queue_search_input.setPlaceholderText("Filename")
        self.queue_search_input.returnPressed.connect(self.search_queue_filename)

        self.queue_find_button = QPushButton("", panel)
        self.queue_find_button.setObjectName("SubtleButton")
        self.queue_find_button.setAccessibleName("Find")
        self.queue_find_button.setToolTip("Find filename")
        self.queue_find_button.setIcon(self._search_icon())
        self.queue_find_button.setIconSize(QSize(18, 18))
        self.queue_find_button.clicked.connect(self.search_queue_filename)
        self.queue_find_button.setFixedSize(42, 34)

        search_row.addWidget(self.queue_search_input, 1)
        search_row.addWidget(self.queue_find_button)

        self.queue_list = QListWidget()
        self.queue_list.setUniformItemSizes(True)
        self.queue_list.itemClicked.connect(self._handle_queue_item_clicked)

        layout.addLayout(header)
        layout.addLayout(search_row)
        layout.addWidget(self.queue_list, 1)
        return panel

    def _build_viewer_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("ViewerSurface")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.viewer_toolbar = self._build_viewer_toolbar()
        self.image_viewer = ImageViewer()
        self.image_viewer.wheel_navigation_requested.connect(
            self._handle_viewer_wheel_navigation
        )
        layout.addWidget(self.viewer_toolbar)
        layout.addWidget(self.image_viewer, 1)
        return panel

    def _build_viewer_toolbar(self) -> QFrame:
        toolbar = QFrame()
        toolbar.setObjectName("ViewerToolbar")
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        current_label = QLabel("Viewer")
        current_label.setObjectName("SectionLabel")
        jump_label = QLabel("Jump")
        jump_label.setObjectName("MutedText")
        self.jump_spinbox = QSpinBox(toolbar)
        self.jump_spinbox.setMinimum(1)
        self.jump_spinbox.setMaximum(1)
        self.jump_spinbox.setFixedWidth(72)
        self.jump_spinbox.lineEdit().returnPressed.connect(self.jump_to_image)
        self.jump_button = QPushButton("Go", toolbar)
        self.jump_button.setObjectName("SubtleButton")
        self.jump_button.clicked.connect(self.jump_to_image)
        self.preserve_zoom_button = QPushButton("Keep Zoom", toolbar)
        self.preserve_zoom_button.setObjectName("SubtleButton")
        self.preserve_zoom_button.setCheckable(True)
        self.preserve_zoom_button.toggled.connect(self.toggle_preserve_zoom)
        self.fit_button = QPushButton("Fit", toolbar)
        self.fit_button.setObjectName("SubtleButton")
        self.fit_button.clicked.connect(self._fit_viewer)

        layout.addWidget(current_label)
        layout.addStretch(1)
        layout.addWidget(jump_label)
        layout.addWidget(self.jump_spinbox)
        layout.addWidget(self.jump_button)
        layout.addWidget(self.preserve_zoom_button)
        layout.addWidget(self.fit_button)
        return toolbar

    def _build_inspector_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("InspectorPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(14)

        self.profile_panel = self._build_profile_panel(panel)
        classification_header = QHBoxLayout()
        classification_header.setContentsMargins(0, 0, 0, 0)
        classification_header.setSpacing(8)
        title = QLabel("Classify")
        title.setObjectName("PanelTitle")
        self.xml_pair_button = QCheckBox("LinkXML", panel)
        self.xml_pair_button.setObjectName("LinkSwitch")
        self.xml_pair_button.setChecked(self.move_xml_pairs)
        self.xml_pair_button.toggled.connect(self._toggle_xml_pair_mode)
        self._sync_xml_pair_button()
        self.classification_columns_combo = QComboBox(panel)
        self.classification_columns_combo.setObjectName("ColumnCombo")
        self.classification_columns_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.classification_columns_combo.setMinimumContentsLength(5)
        for columns in range(
            MIN_CLASSIFICATION_COLUMNS, MAX_CLASSIFICATION_COLUMNS + 1
        ):
            label = "Col" if columns == 1 else "Cols"
            self.classification_columns_combo.addItem(
                f"{columns} {label}", columns
            )
        self.classification_columns_combo.currentIndexChanged.connect(
            self._handle_classification_columns_changed
        )
        self._sync_classification_columns_combo()
        classification_header.addWidget(title)
        classification_header.addStretch(1)
        classification_header.addWidget(self.xml_pair_button)
        classification_header.addWidget(self.classification_columns_combo)

        self.classification_layout = QGridLayout()
        self.classification_layout.setContentsMargins(0, 0, 0, 0)
        self.classification_layout.setSpacing(8)

        progress_title = QLabel("Progress")
        progress_title.setObjectName("PanelTitle")
        self.progress_label = QLabel("0 / 0 complete")
        self.progress_label.setObjectName("MetricLabel")
        self.remaining_label = QLabel("0 remaining")
        self.remaining_label.setObjectName("MetricLabel")

        self.history_title = QLabel("Recent")
        self.history_title.setObjectName("PanelTitle")
        self.history_list = QListWidget()
        self.history_list.setUniformItemSizes(False)
        self.history_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.history_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.history_list.setMinimumHeight(300)
        self.history_list.setMaximumHeight(360)

        layout.addWidget(self.profile_panel)
        layout.addLayout(classification_header)
        layout.addLayout(self.classification_layout)
        layout.addSpacing(6)
        layout.addWidget(progress_title)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.remaining_label)
        layout.addSpacing(6)
        layout.addWidget(self.history_title)
        layout.addWidget(self.history_list)
        layout.addStretch(1)

        # Let the scroll viewport own the width. Preferred/sizeHint content
        # (multi-col classify rows) is wider than the default splitter slot
        # (~310px), which otherwise leaves a permanent horizontal scrollbar
        # covering the panel edge on launch.
        panel.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        container = QFrame()
        container.setObjectName("InspectorPanel")
        container.setMinimumWidth(280)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(scroll)
        return container

    def _build_profile_panel(self, parent: QWidget) -> QFrame:
        panel = QFrame(parent)
        panel.setObjectName("ProfilePanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Profile")
        title.setObjectName("PanelTitle")
        self.profile_combo = QComboBox(panel)
        self.profile_combo.addItems(self.profiles.keys())
        if self.active_profile:
            self.profile_combo.setCurrentText(self.active_profile)
        self.profile_combo.currentTextChanged.connect(self._handle_profile_changed)
        header.addWidget(title)
        header.addWidget(self.profile_combo, 1)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.edit_bindings_button = QPushButton("Keys", panel)
        self.edit_bindings_button.setObjectName("SubtleButton")
        self.edit_bindings_button.clicked.connect(self.configure_bindings)
        self.new_profile_button = QPushButton("New", panel)
        self.new_profile_button.setObjectName("SubtleButton")
        self.new_profile_button.clicked.connect(self.prompt_create_binding_profile)
        self.delete_profile_button = QPushButton("Delete", panel)
        self.delete_profile_button.setObjectName("SubtleButton")
        self.delete_profile_button.clicked.connect(self._request_delete_binding_profile)
        actions.addWidget(self.edit_bindings_button)
        actions.addWidget(self.new_profile_button)
        actions.addWidget(self.delete_profile_button)

        layout.addLayout(header)
        layout.addLayout(actions)
        return panel

    def _render_classification_buttons(self) -> None:
        self._clear_layout(self.classification_layout)
        bindings = self.profiles.get(self.active_profile, {})
        columns = self.classification_columns

        if not bindings:
            empty = QLabel("No keys in this profile")
            empty.setObjectName("MutedText")
            self.classification_layout.addWidget(empty, 0, 0, 1, columns)
            return

        for column in range(MAX_CLASSIFICATION_COLUMNS):
            self.classification_layout.setColumnStretch(column, 0)

        for index, (key, folder) in enumerate(bindings.items()):
            row = QFrame()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)

            key_label = QLabel(key)
            key_label.setObjectName("KeyCap")
            key_label.setFixedWidth(38)
            key_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            button = QPushButton(folder)
            button.setObjectName("ClassifyButton")
            button.setToolTip(folder)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(
                lambda checked=False, value=key: self.classify(value)
            )

            row_layout.addWidget(key_label)
            row_layout.addWidget(button, 1)
            self.classification_layout.addWidget(
                row,
                index // columns,
                index % columns,
            )

        for column in range(columns):
            self.classification_layout.setColumnStretch(column, 1)

    def _normalized_classification_columns(self, value) -> int:
        try:
            columns = int(value)
        except (TypeError, ValueError):
            return MIN_CLASSIFICATION_COLUMNS
        return max(
            MIN_CLASSIFICATION_COLUMNS,
            min(MAX_CLASSIFICATION_COLUMNS, columns),
        )

    def _sync_classification_columns_combo(self) -> None:
        if not hasattr(self, "classification_columns_combo"):
            return
        columns = self.classification_columns
        index = self.classification_columns_combo.findData(columns)
        if index < 0:
            index = 0
        with QSignalBlocker(self.classification_columns_combo):
            self.classification_columns_combo.setCurrentIndex(index)
        column_label = "column" if columns == 1 else "columns"
        self.classification_columns_combo.setToolTip(
            f"Show classify buttons in 1–{MAX_CLASSIFICATION_COLUMNS} "
            f"columns (current: {columns} {column_label})"
        )

    def _handle_classification_columns_changed(self, index: int = 0) -> None:
        if not hasattr(self, "classification_columns_combo"):
            return
        raw = self.classification_columns_combo.itemData(index)
        if raw is None:
            raw = self.classification_columns_combo.currentData()
        columns = self._normalized_classification_columns(raw)
        if columns == self.classification_columns:
            self._sync_classification_columns_combo()
            return
        self.classification_columns = columns
        self.classifier_config["classification_columns"] = columns
        self._save_classifier_config()
        self._sync_classification_columns_combo()
        self._render_classification_buttons()
        column_label = "column" if columns == 1 else "columns"
        self._set_status(f"Classify buttons: {columns} {column_label}")

    def _toggle_xml_pair_mode(self, checked: bool = False) -> None:
        if self._move_in_progress:
            with QSignalBlocker(self.xml_pair_button):
                self.xml_pair_button.setChecked(self.move_xml_pairs)
            self._sync_xml_pair_button()
            self._set_status("Move already in progress")
            return
        self.move_xml_pairs = bool(checked)
        if self.session is not None:
            self.session.move_xml_pairs = self.move_xml_pairs
        self.classifier_config["move_xml_pairs"] = self.move_xml_pairs
        self._save_classifier_config()
        self._sync_xml_pair_button()
        status = (
            "LinkXML enabled"
            if self.move_xml_pairs
            else "LinkXML disabled"
        )
        self._set_status(status)

    def _sync_xml_pair_button(self) -> None:
        if not hasattr(self, "xml_pair_button"):
            return
        with QSignalBlocker(self.xml_pair_button):
            self.xml_pair_button.setChecked(self.move_xml_pairs)
        # Compact fixed label; on/off is carried by the switch indicator.
        self.xml_pair_button.setText("LinkXML")
        self.xml_pair_button.setToolTip(
            "Move matching .xml labels with classified images. Missing labels are ignored."
        )

    def _handle_profile_changed(self, profile_name: str) -> None:
        if not profile_name:
            return
        self.active_profile = profile_name
        active_bindings = dict(self.profiles.get(profile_name, {}))
        self.classifier_config["active_binding_profile"] = profile_name
        self.classifier_config["default_key_bindings"] = active_bindings
        self._save_classifier_config()

        if self.session is not None:
            self.session.key_bindings = active_bindings

        self._render_classification_buttons()
        self._register_shortcuts()
        self._update_status_widgets()
        self.statusBar().showMessage(f"Profile selected: {profile_name}", 2500)

    def _toggle_presentation_mode(self, enabled: bool) -> None:
        self.queue_panel.setVisible(not enabled)
        self.target_button.setVisible(not enabled)
        self.target_path_label.setVisible(not enabled)
        self.refresh_button.setVisible(not enabled)
        self.open_folder_button.setVisible(not enabled)
        self.profile_panel.setVisible(not enabled)
        self.xml_pair_button.setVisible(not enabled)
        self.history_title.setVisible(not enabled)
        self.history_list.setVisible(not enabled)
        self.presentation_button.setText(
            "Exit Presentation" if enabled else "Presentation"
        )
        self.statusBar().showMessage(
            "Presentation mode" if enabled else "Workbench mode", 2500
        )

    def select_source_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select source folder",
            str(self.source_folder or Path.cwd()),
        )
        if not folder:
            return

        self.source_folder = Path(folder)
        if not self._target_manually_selected:
            self.target_folder = self.source_folder
        self._create_session()
        self.session.refresh()
        self.batch_total_count = len(self.session.images)

        self.source_path_label.setText(str(self.source_folder))
        self.target_path_label.setText(str(self.target_folder))
        self._sync_after_session_change("Source loaded")

    def select_target_folder(self) -> None:
        start = self.target_folder or self.source_folder or Path.cwd()
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select target folder",
            str(start),
        )
        if not folder:
            return

        self.target_folder = Path(folder)
        self._target_manually_selected = True
        if self.session is not None:
            self.session.target_folder = self.target_folder
        self.target_path_label.setText(str(self.target_folder))
        self.statusBar().showMessage("Target folder updated", 2500)

    def next_image(self) -> None:
        if not self.session or not self.session.images:
            self._set_status("No image loaded")
            return
        requested_index = min(
            self.session.current_index + 1, len(self.session.images) - 1
        )
        _debug.log_operation(
            "next_image",
            current=self.session.current_index,
            requested=requested_index,
            total=len(self.session.images),
        )
        self._set_current_image_index(requested_index, "Next image")

    def previous_image(self) -> None:
        if not self.session or not self.session.images:
            self._set_status("No image loaded")
            return
        requested_index = max(self.session.current_index - 1, 0)
        self._set_current_image_index(requested_index, "Previous image")

    def skip_image(self) -> None:
        self.next_image()

    def _handle_viewer_wheel_navigation(self, direction: int) -> None:
        if direction < 0:
            self.previous_image()
            return
        self.next_image()

    def refresh_batch(self) -> None:
        if not self.session:
            self._set_status("Select a source folder first")
            return
        self.session.refresh()
        self.batch_total_count = max(
            self.batch_total_count,
            len(self.session.images) + len(self.session.history),
        )
        self._sync_after_session_change("Queue refreshed")

    def open_current_folder(self) -> None:
        if not self.source_folder:
            self._set_status("Select a source folder first")
            return
        self._folder_launcher(self.source_folder)
        self._set_status(f"Opened {self.source_folder}")

    def jump_to_image(self) -> None:
        if not self.session or not self.session.images:
            self._set_status("No image loaded")
            return

        requested_index = self.jump_spinbox.value() - 1
        self._set_current_image_index(
            requested_index,
            f"Selected image {requested_index + 1}",
        )

    def _set_current_image_index(
        self,
        requested_index: int,
        message: str,
        remember_previous: bool = True,
    ) -> bool:
        if not self.session or not self.session.images:
            self._set_status("No image loaded")
            return False

        if requested_index < 0 or requested_index >= len(self.session.images):
            self._set_status(
                f"Jump must be between 1 and {len(self.session.images)}"
            )
            return False

        current = self.session.current_image()
        target = self.session.images[requested_index]
        if remember_previous and current is not None and current != target:
            self._remember_previous_image(current)

        self.session.current_index = requested_index
        self._sync_after_session_change(message)
        return True

    def _remember_previous_image(self, image_path: Path) -> None:
        self._previous_image_paths.append(image_path)
        del self._previous_image_paths[:-5]

    def search_queue_filename(self) -> None:
        if not self.session or not self.session.images:
            self._set_status("No image loaded")
            return

        requested_name = self.queue_search_input.text().strip()
        if not requested_name:
            self._set_status("Enter a filename")
            return

        requested_key = requested_name.casefold()
        search_full_name = bool(Path(requested_name).suffix)
        for index, path in enumerate(self.session.images):
            candidate = path.name if search_full_name else path.stem
            if candidate.casefold() == requested_key:
                self._set_current_image_index(index, f"Selected {path.name}")
                return

        self._set_status(f"File not found: {requested_name}")

    def back_to_previous_image(self) -> None:
        if not self.session or not self.session.images:
            self._set_status("No image loaded")
            return

        if not self._previous_image_paths:
            self._set_status("No previous image")
            return

        previous = self._previous_image_paths.pop()
        try:
            requested_index = self.session.images.index(previous)
        except ValueError:
            self._previous_image_paths.clear()
            self._set_status("Previous image is no longer available")
            return

        self._set_current_image_index(
            requested_index,
            f"Returned to {previous.name}",
            remember_previous=False,
        )

    def toggle_preserve_zoom(self, enabled: bool) -> None:
        self.image_viewer.set_preserve_view(enabled)
        self.preserve_zoom_button.setText("Keep Zoom On" if enabled else "Keep Zoom")
        self._set_status("Keeping zoom" if enabled else "Fit new images")

    def _fit_viewer(self) -> None:
        self.image_viewer.fit_to_window()
        self._set_status("Fit image to window")

    def configure_bindings(self) -> None:
        dialog, row_list = self._build_key_bindings_dialog()

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            bindings = self._collect_key_binding_rows(row_list)
        except ValueError as exc:
            QMessageBox.warning(
                self,
                "Invalid binding",
                str(exc),
            )
            return
        except KeyError as exc:
            QMessageBox.warning(self, "Duplicate key", f"Key '{exc.args[0]}' is duplicated.")
            return

        self.update_active_bindings(bindings)
        self._set_status(f"Saved {len(bindings)} key bindings")

    def _build_key_bindings_dialog(self) -> tuple[QDialog, QListWidget]:
        dialog = QDialog(self)
        dialog.setObjectName("WorkbenchDialog")
        dialog.setWindowTitle(f"Edit Keys - {self.active_profile}")
        dialog.setMinimumSize(780, 520)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(16)

        header = QFrame(dialog)
        header.setObjectName("DialogHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        title = QLabel("Key Bindings", header)
        title.setObjectName("DialogTitle")
        subtitle = QLabel(f"Profile: {self.active_profile}", header)
        subtitle.setObjectName("DialogSubtitle")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)

        form_panel = QFrame(dialog)
        form_panel.setObjectName("DialogFormPanel")
        form_layout = QVBoxLayout(form_panel)
        form_layout.setContentsMargins(14, 14, 14, 14)
        form_layout.setSpacing(8)

        header_row = QFrame(form_panel)
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)
        drag_header = QLabel("", header_row)
        drag_header.setFixedWidth(40)
        key_header = QLabel("Key", header_row)
        key_header.setObjectName("KeyColumnHeader")
        key_header.setFixedWidth(76)
        folder_header = QLabel("Target Folder", header_row)
        folder_header.setObjectName("FolderColumnHeader")
        delete_header = QLabel("", header_row)
        delete_header.setFixedWidth(70)
        header_layout.addWidget(drag_header)
        header_layout.addWidget(key_header)
        header_layout.addWidget(folder_header, 1)
        header_layout.addWidget(delete_header)

        row_list = QListWidget(form_panel)
        row_list.setObjectName("KeyBindingsList")
        row_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        row_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        row_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        row_list.setUniformItemSizes(False)
        row_list.setSpacing(2)
        row_list.setMinimumHeight(260)
        row_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        row_list.model().rowsMoved.connect(
            lambda *_args, list_widget=row_list: self._clear_key_binding_row_selection(
                list_widget
            )
        )

        form_layout.addWidget(header_row)
        form_layout.addWidget(row_list)

        def add_mapping_row(key: str = "", folder: str = "") -> None:
            row_widget = KeyBindingRow(key, folder, row_list)
            item = QListWidgetItem(row_list)
            item.setSizeHint(QSize(0, 36))
            row_list.addItem(item)
            row_list.setItemWidget(item, row_widget)
            row_widget.delete_button.clicked.connect(
                lambda checked=False, row_item=item: self._delete_key_binding_row(
                    row_list,
                    row_item,
                )
            )

        current_bindings = self.profiles.get(self.active_profile, {})
        binding_items = list(current_bindings.items())
        for key, folder in binding_items:
            add_mapping_row(key, folder)

        empty_rows = max(2, 6 - len(binding_items))
        for _row in range(empty_rows):
            add_mapping_row()

        action_row = QFrame(dialog)
        action_row.setObjectName("KeyBindingsActionRow")
        action_layout = QHBoxLayout(action_row)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)

        add_button = QPushButton("Add Mapping", action_row)
        add_button.setObjectName("AddMappingButton")
        add_button.clicked.connect(lambda checked=False: add_mapping_row())

        sort_button = QPushButton("Sort by Key", action_row)
        sort_button.setObjectName("SortMappingButton")
        sort_button.setToolTip("Letters aAbB, then digits 0-9, then other characters")
        sort_button.clicked.connect(
            lambda checked=False: self._sort_key_binding_rows(row_list)
        )

        action_layout.addWidget(add_button)
        action_layout.addWidget(sort_button)
        action_layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.setObjectName("DialogActions")

        def accept_valid_bindings() -> None:
            try:
                self._collect_key_binding_rows(row_list)
            except ValueError as exc:
                QMessageBox.warning(dialog, "Invalid binding", str(exc))
                return
            except KeyError as exc:
                QMessageBox.warning(
                    dialog,
                    "Duplicate key",
                    f"Key '{exc.args[0]}' is duplicated.",
                )
                return
            dialog.accept()

        buttons.accepted.connect(accept_valid_bindings)
        buttons.rejected.connect(dialog.reject)

        layout.addWidget(header)
        layout.addWidget(form_panel)
        layout.addWidget(action_row)
        layout.addWidget(buttons)
        self._size_key_bindings_dialog_for_rows(dialog, row_list, row_list.count())
        return dialog, row_list

    @staticmethod
    def _key_binding_sort_key(key: str) -> tuple:
        """Sort key for mapping rows: aAbB, then digits, then other chars, empty last."""
        text = str(key).strip()
        if not text:
            return (3, "", 0, "")
        ch = text[0]
        if ch.isalpha():
            # a, A, b, B ... — group by letter, lowercase before uppercase
            return (0, ch.casefold(), 0 if ch.islower() else 1, ch)
        if ch.isdigit():
            return (1, ch, 0, ch)
        return (2, ch, 0, ch)

    def _sort_key_binding_rows(self, row_list: QListWidget) -> None:
        rows = []
        row_widgets = []
        for row in range(row_list.count()):
            widget = row_list.itemWidget(row_list.item(row))
            if not isinstance(widget, KeyBindingRow):
                continue
            row_widgets.append(widget)
            rows.append((widget.key_edit.text(), widget.folder_edit.text()))

        rows.sort(key=lambda values: self._key_binding_sort_key(values[0]))
        for widget, (key, folder) in zip(row_widgets, rows):
            widget.key_edit.setText(key)
            widget.folder_edit.setText(folder)

        self._clear_key_binding_row_selection(row_list)

    def _delete_key_binding_row(
        self,
        row_list: QListWidget,
        item: QListWidgetItem,
    ) -> None:
        row = row_list.row(item)
        if row < 0:
            return
        removed = row_list.takeItem(row)
        if removed is not None:
            del removed

    def _move_key_binding_row(
        self,
        row_list: QListWidget,
        from_row: int,
        to_row: int,
    ) -> bool:
        if from_row < 0 or from_row >= row_list.count():
            return False
        to_row = max(0, min(to_row, row_list.count() - 1))
        if from_row == to_row:
            return True

        item = row_list.item(from_row)
        widget = row_list.itemWidget(item)
        row_list.removeItemWidget(item)
        moved = row_list.takeItem(from_row)
        row_list.insertItem(to_row, moved)
        row_list.setItemWidget(moved, widget)
        self._clear_key_binding_row_selection(row_list)
        return True

    def _clear_key_binding_row_selection(self, row_list: QListWidget) -> None:
        with QSignalBlocker(row_list):
            row_list.clearSelection()
            row_list.setCurrentRow(-1)

    def _collect_key_binding_rows(self, row_list: QListWidget) -> dict[str, str]:
        bindings: dict[str, str] = {}
        target_folders: dict[str, str] = {}
        for row in range(row_list.count()):
            item = row_list.item(row)
            row_widget = row_list.itemWidget(item)
            if not isinstance(row_widget, KeyBindingRow):
                continue
            key = row_widget.key_edit.text().strip()
            folder = row_widget.folder_edit.text().strip()
            if not key and not folder:
                continue
            if len(key) != 1 or not folder:
                raise ValueError("Each binding needs one key and one target folder.")
            if key in bindings:
                raise KeyError(key)
            normalized_folder = folder.casefold()
            existing_folder = target_folders.get(normalized_folder)
            if existing_folder is not None:
                if existing_folder == folder:
                    raise ValueError(f"Target folder is duplicated: '{folder}'")
                raise ValueError(
                    "Target folders differ only by case: "
                    f"'{existing_folder}' and '{folder}'"
                )
            target_folders[normalized_folder] = folder
            bindings[key] = folder
        return bindings

    def update_active_bindings(self, bindings: dict[str, str]) -> None:
        normalized = {
            str(key).strip(): str(folder).strip()
            for key, folder in bindings.items()
            if len(str(key).strip()) == 1 and str(folder).strip()
        }
        self.profiles[self.active_profile] = normalized
        self.classifier_config["binding_profiles"] = deepcopy(self.profiles)
        self.classifier_config["default_key_bindings"] = deepcopy(normalized)
        self.classifier_config["active_binding_profile"] = self.active_profile
        if self.session is not None:
            self.session.key_bindings = dict(normalized)
        self._save_classifier_config()
        self._render_classification_buttons()
        self._register_shortcuts()
        self._update_status_widgets()
        self._refresh_profile_combo()

    def prompt_create_binding_profile(self) -> None:
        profile_name = self._prompt_profile_name()
        if profile_name is None:
            return
        self.create_binding_profile(profile_name)

    def _prompt_profile_name(self) -> str | None:
        dialog = QDialog(self)
        dialog.setObjectName("WorkbenchDialog")
        dialog.setWindowTitle("New Profile")
        dialog.setMinimumWidth(420)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)

        title = QLabel("New Profile", dialog)
        title.setObjectName("DialogTitle")
        name_label = QLabel("Profile Name", dialog)
        name_label.setObjectName("FieldLabel")
        name_edit = QLineEdit(dialog)
        name_edit.setObjectName("ProfileNameInput")
        name_edit.setMinimumHeight(34)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.setObjectName("DialogActions")
        create_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if create_button is not None:
            create_button.setText("Create")
            create_button.setObjectName("PrimaryButton")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        layout.addWidget(title)
        layout.addWidget(name_label)
        layout.addWidget(name_edit)
        layout.addWidget(buttons)
        name_edit.setFocus()

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return name_edit.text()

    def create_binding_profile(self, profile_name: str) -> bool:
        profile_name = str(profile_name).strip()
        if not profile_name:
            self._set_status("Profile name cannot be empty")
            return False
        if profile_name in self.profiles:
            self._set_status(f"Profile already exists: {profile_name}")
            return False

        self.profiles[profile_name] = dict(self.profiles.get(self.active_profile, {}))
        self.active_profile = profile_name
        self.classifier_config["binding_profiles"] = deepcopy(self.profiles)
        self.classifier_config["active_binding_profile"] = self.active_profile
        self.classifier_config["default_key_bindings"] = deepcopy(
            self.profiles[self.active_profile]
        )
        if self.session is not None:
            self.session.key_bindings = dict(self.profiles[self.active_profile])
        self._save_classifier_config()
        self._refresh_profile_combo()
        self._render_classification_buttons()
        self._register_shortcuts()
        self._update_status_widgets()
        self._set_status(f"Created profile: {profile_name}")
        return True

    def delete_binding_profile(self, confirm: bool = True) -> bool:
        if self.active_profile == DEFAULT_PROFILE_NAME:
            self._set_status("Default profile cannot be deleted")
            return False
        if self.active_profile not in self.profiles:
            return False

        if confirm:
            answer = QMessageBox.question(
                self,
                "Delete key profile",
                f"Delete profile '{self.active_profile}'?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False

        deleted_profile = self.active_profile
        del self.profiles[deleted_profile]
        self.active_profile = DEFAULT_PROFILE_NAME
        if self.active_profile not in self.profiles:
            self.profiles[self.active_profile] = {}

        self.classifier_config["binding_profiles"] = deepcopy(self.profiles)
        self.classifier_config["active_binding_profile"] = self.active_profile
        self.classifier_config["default_key_bindings"] = deepcopy(
            self.profiles[self.active_profile]
        )
        if self.session is not None:
            self.session.key_bindings = dict(self.profiles[self.active_profile])
        self._save_classifier_config()
        self._refresh_profile_combo()
        self._render_classification_buttons()
        self._register_shortcuts()
        self._update_status_widgets()
        self._set_status(f"Deleted profile: {deleted_profile}")
        return True

    def _request_delete_binding_profile(self) -> None:
        self.delete_binding_profile(confirm=True)

    def classify(self, key: str, enforce_focus: bool = False) -> None:
        _debug.log_operation(
            "classify",
            key=key,
            enforce_focus=enforce_focus,
            move_in_progress=self._move_in_progress,
            has_session=bool(self.session),
        )

        if self._move_in_progress:
            _debug.log_state("classify", action="skip", reason="move_in_progress")
            self._set_status("Move already in progress")
            return
        if not self.session:
            self._set_status("Select a source folder first")
            return
        current = self.session.current_image()
        if current is not None and self.image_viewer.is_loading_path(current):
            _debug.log_state("classify", action="skip", reason="image_loading")
            self._set_status("Image is still loading")
            return
        if enforce_focus:
            if not self._classification_shortcut_allowed():
                return
        elif QApplication.activeModalWidget() is not None:
            return

        _debug.log_state("classify", action="start_move", current_image=current.name if current else None)
        self._move_in_progress = True
        self._sync_move_controls_enabled()
        self._set_status("Moving image...")
        self._run_move_operation(
            self.session.classify_current,
            self._handle_classify_finished,
            key,
        )

    def undo_last_action(self) -> None:
        if not self.session:
            self._set_status("No session to undo")
            return

        if self._move_in_progress:
            self._set_status("Move already in progress")
            return

        self._move_in_progress = True
        self._sync_move_controls_enabled()
        self._set_status("Restoring image...")
        self._run_move_operation(
            self.session.undo_last,
            self._handle_undo_finished,
        )

    def _create_session(self) -> None:
        if self.source_folder is None:
            return
        if self.target_folder is None:
            self.target_folder = self.source_folder

        self._previous_image_paths.clear()
        self.session = ClassifierSession(
            source_folder=self.source_folder,
            target_folder=self.target_folder,
            supported_formats=list(
                self.classifier_config.get("supported_formats", [".jpg", ".png"])
            ),
            key_bindings=dict(self.profiles.get(self.active_profile, {})),
            move_xml_pairs=self.move_xml_pairs,
        )

    def _sync_after_session_change(self, message: str) -> None:
        self._populate_queue()
        self._load_current_image()
        self._update_progress()
        self._update_status_widgets()
        self._set_status(message)

    def _populate_queue(self) -> None:
        images = self.session.images if self.session else []
        signature = tuple(str(path) for path in images)
        if signature != self._queue_signature:
            self.queue_list.clear()
            for path in images:
                item = QListWidgetItem(path.name)
                item.setToolTip(str(path))
                self.queue_list.addItem(item)
            self._queue_signature = signature

        self.queue_count_label.setText(f"{len(images)} images")
        if self.session and images:
            row = min(self.session.current_index, len(images) - 1)
            with QSignalBlocker(self.queue_list):
                self.queue_list.setCurrentRow(row)
            self.jump_spinbox.setMaximum(len(images))
            self.jump_spinbox.setValue(row + 1)
        else:
            self.jump_spinbox.setMaximum(1)
            self.jump_spinbox.setValue(1)

    def _load_current_image(self) -> None:
        current = self.session.current_image() if self.session else None
        _debug.log_operation(
            "_load_current_image",
            current=current.name if current else None,
            previous=self._current_loaded_image.name if self._current_loaded_image else None,
        )

        if current is None:
            self.image_viewer.clear(
                "Batch complete. Select another source folder or undo the last move."
            )
            self._current_loaded_image = None
            self.setWindowTitle("ARS Image Annotation Workbench")
            return

        if current != self._current_loaded_image:
            _debug.log_state("_load_current_image", action="load", path=current.name)
            self.image_viewer.load_image(current)
            self._current_loaded_image = current
        else:
            _debug.log_state("_load_current_image", action="skip", reason="already_loaded")
        self.setWindowTitle(f"ARS Image Annotation Workbench - {current.name}")

    def _update_progress(self) -> None:
        remaining = len(self.session.images) if self.session else 0
        if self.batch_total_count < remaining:
            self.batch_total_count = remaining
        completed = max(self.batch_total_count - remaining, 0)
        self.progress_label.setText(f"{completed} / {self.batch_total_count} complete")
        self.remaining_label.setText(f"{remaining} remaining")

    def _record_operation(self, text: str) -> None:
        self.recent_operations.insert(0, text)
        del self.recent_operations[6:]
        self.history_list.clear()
        for operation in self.recent_operations:
            item = QListWidgetItem(operation)
            item.setToolTip(operation)
            self.history_list.addItem(item)

    def _format_move_record(self, record: MoveRecord) -> str:
        xml_marker = " + XML" if record.xml_target is not None else ""
        return f"{record.key} -> {record.category}{xml_marker}: {record.source.name}"

    def _handle_queue_item_clicked(self, item: QListWidgetItem) -> None:
        if not self.session:
            return
        row = self.queue_list.row(item)
        if row < 0:
            return
        self._set_current_image_index(row, f"Selected {item.text()}")

    def _register_shortcuts(self) -> None:
        for shortcut in self._shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._shortcuts = []
        self._shortcut_registry = []

        callbacks = {
            "next": self.next_image,
            "previous": self.previous_image,
            "skip": self.skip_image,
            "undo": self.undo_last_action,
            "refresh": self.refresh_batch,
            "open_folder": self.select_source_folder,
            "exit": self.close,
        }
        shortcuts = self.classifier_config.get("shortcuts", {})
        action_sequences = set()
        for action_name, shortcut_data in shortcuts.items():
            callback = callbacks.get(action_name)
            if not callback:
                continue
            for key in shortcut_data.get("keys", []):
                sequence = self._to_key_sequence(key)
                if sequence.isEmpty():
                    continue
                action_sequences.add(sequence.toString())
                self._add_shortcut(sequence, callback, action_name)

        conflicts = []
        for key in self.profiles.get(self.active_profile, {}):
            sequence = self._to_key_sequence(key)
            if sequence.isEmpty():
                continue
            if sequence.toString() in action_sequences:
                conflicts.append(key)
                continue
            self._add_shortcut(
                sequence,
                lambda value=key: self.classify(value, enforce_focus=True),
                f"classify:{key}",
            )

        if conflicts:
            self._record_operation(
                "Shortcut conflict: " + ", ".join(sorted(conflicts))
            )

    def _add_shortcut(self, sequence: QKeySequence, callback, action_name: str) -> None:
        shortcut = QShortcut(sequence, self)
        shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut.activated.connect(callback)
        self._shortcuts.append(shortcut)
        self._shortcut_registry.append((sequence.toString(), action_name))

    def _to_key_sequence(self, key: str) -> QKeySequence:
        normalized = str(key).strip()
        if not normalized:
            return QKeySequence()
        replacements = {
            "Control-": "Ctrl+",
            "Alt-": "Alt+",
            "Shift-": "Shift+",
        }
        for source, target in replacements.items():
            if normalized.startswith(source):
                normalized = target + normalized[len(source) :].upper()
                break
        else:
            if len(normalized) == 1:
                if normalized.isalpha() and normalized.isupper():
                    normalized = f"Shift+{normalized}"
                else:
                    normalized = normalized.upper()
        return QKeySequence(normalized)

    def _focus_blocks_classification(self) -> bool:
        focused = QApplication.focusWidget()
        if isinstance(focused, (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox)):
            return True
        if QApplication.activeModalWidget() is not None:
            return True
        return False

    def _classification_shortcut_allowed(self) -> bool:
        if self._focus_blocks_classification():
            return False

        focused = QApplication.focusWidget()
        if focused is None:
            return True

        return focused in {
            self,
            self.image_viewer,
            self.image_viewer.viewport(),
            self.centralWidget(),
        }

    def _build_status_bar(self) -> None:
        self.current_file_status = QLabel("No file")
        self.current_file_status.setObjectName("MetricLabel")
        self.profile_status = QLabel(f"Profile: {self.active_profile}")
        self.profile_status.setObjectName("MetricLabel")
        self.shortcut_status = QLabel(self._shortcut_hint_text())
        self.shortcut_status.setObjectName("MetricLabel")
        self.statusBar().addPermanentWidget(self.current_file_status, 2)
        self.statusBar().addPermanentWidget(self.profile_status, 1)
        self.statusBar().addPermanentWidget(self.shortcut_status, 2)

    def _update_status_widgets(self) -> None:
        if not hasattr(self, "current_file_status"):
            return

        current = self.session.current_image() if self.session else None
        total = len(self.session.images) if self.session else 0
        if current is None:
            self.current_file_status.setText("No file")
        else:
            index = self.session.current_index + 1
            self.current_file_status.setText(f"{index} / {total}: {current.name}")

        self.profile_status.setText(f"Profile: {self.active_profile}")
        self.shortcut_status.setText(self._shortcut_hint_text())

    def _shortcut_hint_text(self) -> str:
        bindings = self.profiles.get(self.active_profile, {})
        class_keys = "/".join(bindings.keys())
        if class_keys:
            return f"Classify: {class_keys}   Undo: U   Refresh: F5   Jump: Enter"
        return "No classification keys"

    def _save_classifier_config(self) -> None:
        for key, value in self.classifier_config.items():
            self.config_manager.set(f"image_classifier.{key}", value)
        self.config_manager.save()

    def _sync_move_controls_enabled(self) -> None:
        if hasattr(self, "xml_pair_button"):
            self.xml_pair_button.setEnabled(not self._move_in_progress)

    def _show_profile_warnings(self) -> None:
        if self.profile_warnings:
            self._record_operation("; ".join(self.profile_warnings))

    def _refresh_profile_combo(self) -> None:
        with QSignalBlocker(self.profile_combo):
            self.profile_combo.clear()
            self.profile_combo.addItems(self.profiles.keys())
            self.profile_combo.setCurrentText(self.active_profile)

    def _path_label(self, text: str) -> QLabel:
        return ElidedPathLabel(text)

    def _search_icon(self) -> QIcon:
        pixmap = QPixmap(18, 18)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor("#d7dde6"), 2))
            painter.drawEllipse(3, 3, 9, 9)
            painter.drawLine(11, 11, 15, 15)
        finally:
            painter.end()

        return QIcon(pixmap)

    def _size_key_bindings_dialog_for_rows(
        self,
        dialog: QDialog,
        row_list: QListWidget,
        row_count: int,
    ) -> None:
        base_dialog_height = 520
        base_list_height = 260
        row_height = 36
        visible_rows = max(6, row_count)
        desired_list_height = (
            8
            + visible_rows * row_height
            + max(0, visible_rows - 1) * row_list.spacing()
        )

        screen = dialog.screen() or self.screen() or QApplication.primaryScreen()
        screen_height = screen.availableGeometry().height() if screen else 900
        max_dialog_height = max(base_dialog_height, int(screen_height * 0.9))

        desired_dialog_height = base_dialog_height + max(
            0,
            desired_list_height - base_list_height,
        )
        target_dialog_height = min(desired_dialog_height, max_dialog_height)
        target_list_height = max(
            base_list_height,
            target_dialog_height - (base_dialog_height - base_list_height),
        )

        row_list.setMinimumHeight(target_list_height)
        dialog.resize(dialog.minimumWidth(), target_dialog_height)

    def _set_status(self, text: str) -> None:
        self.statusBar().showMessage(text, 3500)

    def _launch_folder(self, folder: Path) -> None:
        subprocess.Popen(["explorer", str(folder)])

    def _run_move_operation(self, operation, callback, *args) -> None:
        thread = QThread(self)
        worker = _MoveWorker(operation, *args)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(callback)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # Bound slot (not a lambda): receiver affinity is explicitly self, so
        # the queued call is guaranteed on the main thread; the identity guard
        # inside prevents an old thread's late finished from clearing a newer
        # move thread.
        thread.finished.connect(self._handle_move_thread_finished)
        self._move_thread = thread
        self._move_worker = worker
        thread.start()

    @Slot()
    def _handle_move_thread_finished(self) -> None:
        self._clear_move_thread(self.sender())

    def _handle_classify_finished(self, record: MoveRecord | None, error: object) -> None:
        _debug.log_operation(
            "_handle_classify_finished",
            has_record=record is not None,
            has_error=error is not None,
            record_key=record.key if record else None,
            record_category=record.category if record else None,
        )

        self._move_in_progress = False
        self._sync_move_controls_enabled()
        if error is not None:
            if isinstance(error, KeyNotBoundError):
                self._set_status(str(error))
            elif isinstance(error, NoCurrentImageError):
                self._set_status("No image selected")
            elif isinstance(error, ClassifierCoreError):
                self._record_operation(f"Error: {error}")
                self._set_status(str(error))
            else:
                self._record_operation(f"Error: {error}")
                self._set_status(str(error))
            return

        self._record_operation(self._format_move_record(record))
        _debug.log_state("_handle_classify_finished", action="sync_after_session_change")
        self._sync_after_session_change(f"Moved to {record.category}")

    def _handle_undo_finished(self, record: MoveRecord | None, error: object) -> None:
        self._move_in_progress = False
        self._sync_move_controls_enabled()
        if error is not None:
            if isinstance(error, NoCurrentImageError):
                self._set_status("No move to undo")
            elif isinstance(error, ClassifierCoreError):
                self._record_operation(f"Undo failed: {error}")
                self._set_status(str(error))
            else:
                self._record_operation(f"Undo failed: {error}")
                self._set_status(str(error))
            return

        self._record_operation(f"UNDO: {record.source.name}")
        self._sync_after_session_change("Undo restored latest move")

    def _clear_move_thread(self, thread: QThread) -> None:
        if self._move_thread is thread:
            self._move_thread = None
            self._move_worker = None

    def closeEvent(self, event) -> None:
        if self._move_thread is not None:
            self._move_thread.quit()
            self._move_thread.wait(1500)
            self._move_worker = None
        self.image_viewer.shutdown()
        super().closeEvent(event)

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.deleteLater()
