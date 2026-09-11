import json
import os
import subprocess
import sys
import tempfile
import threading
import textwrap
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage, QPainter, QWheelEvent
from PySide6.QtCore import QPoint, QPointF, Qt, QThread, Slot
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QCheckBox
from PySide6.QtWidgets import QComboBox
from PySide6.QtWidgets import QDialog
from PySide6.QtWidgets import QDialogButtonBox
from PySide6.QtWidgets import QLabel
from PySide6.QtWidgets import QPushButton
from PySide6.QtWidgets import QScrollArea

from classifier_core import MoveRecord
from config_manager import ConfigManager
from qt_image_viewer import ImageViewer, _HqResizeWorker, _ImageLoadWorker
from qt_theme import APP_STYLESHEET
from qt_workbench import AnnotationWorkbench


class _FakeViewer:
    def __init__(self):
        self.loaded = []
        self.cleared = []
        self.preserve_view_values = []

    def load_image(self, path):
        self.loaded.append(Path(path))

    def clear(self, message="No image loaded"):
        self.cleared.append(message)

    def is_loading_path(self, path):
        return False

    def shutdown(self):
        pass

    def set_preserve_view(self, enabled):
        self.preserve_view_values.append(enabled)


class _SlowSession:
    def __init__(self, source):
        self.source = Path(source)
        self.images = [self.source / "a.jpg", self.source / "b.jpg"]
        self.current_index = 0
        self.history = []
        self.move_xml_pairs = False

    def current_image(self):
        return self.images[self.current_index] if self.images else None

    def classify_current(self, key):
        time.sleep(0.2)
        source = self.images.pop(self.current_index)
        target = self.source.parent / "classified" / "PT" / source.name
        record = MoveRecord(source=source, target=target, key=key, category="PT")
        self.history.append(record)
        return record

    def undo_last(self):
        time.sleep(0.2)
        record = self.history.pop()
        self.images.insert(self.current_index, record.source)
        return record


class QtWorkbenchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _write_config(self, root, image_classifier):
        config_path = Path(root) / "config.json"
        config_path.write_text(
            json.dumps({"image_classifier": image_classifier}),
            encoding="utf-8",
        )
        return config_path

    def _workbench(self, config_path):
        window = AnnotationWorkbench(ConfigManager(str(config_path)))
        window.image_viewer = _FakeViewer()
        return window

    def _loaded_workbench(self, tmp, names=("a.jpg", "B.JPG", "c.png")):
        root = Path(tmp)
        source = root / "pending"
        source.mkdir()
        for name in names:
            (source / name).write_bytes(b"x")
        config_path = self._write_config(
            tmp,
            {
                "supported_formats": [".jpg", ".png"],
                "default_key_bindings": {"p": "PT"},
                "binding_profiles": {"default": {"p": "PT"}},
                "active_binding_profile": "default",
                "window_size": [1200, 800],
                "shortcuts": {},
            },
        )
        window = self._workbench(config_path)
        window.source_folder = source
        window.target_folder = root / "classified"
        window._create_session()
        window.session.refresh()
        window.batch_total_count = len(window.session.images)
        window._sync_after_session_change("loaded")
        return window, source

    def _process_events_until(self, predicate, timeout=1.0):
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            # Process events multiple times to handle queued connections
            for _ in range(5):
                self.app.processEvents()
            if predicate():
                return True
            time.sleep(0.01)
        # Final event processing burst
        for _ in range(10):
            self.app.processEvents()
        return predicate()

    def _wheel_event(self, delta_y, modifiers=Qt.KeyboardModifier.NoModifier):
        return QWheelEvent(
            QPointF(12, 12),
            QPointF(12, 12),
            QPoint(0, 0),
            QPoint(0, delta_y),
            Qt.MouseButton.NoButton,
            modifiers,
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )

    def _dialog_key_row_texts(self, row_list):
        rows = []
        for row in range(row_list.count()):
            item = row_list.item(row)
            widget = row_list.itemWidget(item)
            rows.append((widget.key_edit.text(), widget.folder_edit.text()))
        return rows

    def test_initial_profile_migration_is_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )

            window = AnnotationWorkbench(ConfigManager(str(config_path)))
            window.close()

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            image_config = saved["image_classifier"]
            self.assertEqual(image_config["active_binding_profile"], "default")
            self.assertEqual(
                image_config["binding_profiles"], {"default": {"p": "PT"}}
            )
            self.assertEqual(image_config["default_key_bindings"], {"p": "PT"})

    def test_classification_shortcut_conflict_keeps_action_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {"next": {"keys": ["p"]}},
                },
            )

            window = self._workbench(config_path)
            p_shortcuts = [
                shortcut
                for shortcut in window._shortcuts
                if shortcut.key().toString().casefold() == "p"
            ]
            window.close()

            self.assertEqual(len(p_shortcuts), 1)
            self.assertIn("Shortcut conflict: p", window.recent_operations)

    def test_classification_shortcuts_keep_letter_case_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "lower_pt", "P": "upper_pt"},
                    "binding_profiles": {
                        "default": {"p": "lower_pt", "P": "upper_pt"}
                    },
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )

            window = self._workbench(config_path)
            shortcut_registry = list(window._shortcut_registry)
            window.close()

            self.assertIn(("P", "classify:p"), shortcut_registry)
            self.assertIn(("Shift+P", "classify:P"), shortcut_registry)

    def test_classification_buttons_display_case_sensitive_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "lower_pt", "P": "upper_pt"},
                    "binding_profiles": {
                        "default": {"p": "lower_pt", "P": "upper_pt"}
                    },
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )

            window = self._workbench(config_path)
            key_caps = [
                label.text()
                for label in window.findChildren(QLabel, "KeyCap")
            ]
            hint_text = window._shortcut_hint_text()
            window.close()

            self.assertEqual(key_caps[:2], ["p", "P"])
            self.assertIn("Classify: p/P", hint_text)

    def test_classification_buttons_toggle_between_one_and_two_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {
                        "p": "lower_pt",
                        "P": "upper_pt",
                    },
                    "binding_profiles": {
                        "default": {"p": "lower_pt", "P": "upper_pt"}
                    },
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )

            window = self._workbench(config_path)
            first = window.classification_layout.itemAtPosition(0, 0).widget()
            second = window.classification_layout.itemAtPosition(1, 0).widget()

            self.assertEqual(window.classification_columns, 1)
            self.assertIsInstance(window.classification_columns_combo, QComboBox)
            self.assertEqual(window.classification_columns_combo.currentData(), 1)
            self.assertEqual(first.findChild(QLabel, "KeyCap").text(), "p")
            self.assertEqual(second.findChild(QLabel, "KeyCap").text(), "P")

            window.classification_columns_combo.setCurrentIndex(
                window.classification_columns_combo.findData(2)
            )
            first = window.classification_layout.itemAtPosition(0, 0).widget()
            second = window.classification_layout.itemAtPosition(0, 1).widget()
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            window.close()

            self.assertEqual(window.classification_columns, 2)
            self.assertEqual(window.classification_columns_combo.currentData(), 2)
            self.assertEqual(first.findChild(QLabel, "KeyCap").text(), "p")
            self.assertEqual(second.findChild(QLabel, "KeyCap").text(), "P")
            self.assertEqual(
                first.findChild(QPushButton, "ClassifyButton").toolTip(),
                "lower_pt",
            )
            self.assertEqual(
                saved["image_classifier"]["classification_columns"],
                2,
            )

    def test_classification_buttons_restore_persisted_two_column_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"a": "AF", "b": "BM", "c": "BC"},
                    "binding_profiles": {
                        "default": {"a": "AF", "b": "BM", "c": "BC"}
                    },
                    "active_binding_profile": "default",
                    "classification_columns": 2,
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )

            window = self._workbench(config_path)
            third = window.classification_layout.itemAtPosition(1, 0).widget()
            window.close()

            self.assertEqual(window.classification_columns, 2)
            self.assertEqual(window.classification_columns_combo.currentData(), 2)
            self.assertEqual(third.findChild(QLabel, "KeyCap").text(), "c")

    def test_classification_buttons_support_four_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {
                        "a": "A",
                        "b": "B",
                        "c": "C",
                        "d": "D",
                    },
                    "binding_profiles": {
                        "default": {"a": "A", "b": "B", "c": "C", "d": "D"}
                    },
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )

            window = self._workbench(config_path)
            window.classification_columns_combo.setCurrentIndex(
                window.classification_columns_combo.findData(4)
            )
            widgets = [
                window.classification_layout.itemAtPosition(0, col).widget()
                for col in range(4)
            ]
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            window.close()

            self.assertEqual(window.classification_columns, 4)
            self.assertEqual(
                [widget.findChild(QLabel, "KeyCap").text() for widget in widgets],
                ["a", "b", "c", "d"],
            )
            self.assertEqual(
                saved["image_classifier"]["classification_columns"],
                4,
            )

    def test_classification_columns_normalize_out_of_range_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"a": "A"},
                    "binding_profiles": {"default": {"a": "A"}},
                    "active_binding_profile": "default",
                    "classification_columns": 9,
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )

            window = self._workbench(config_path)
            window.close()

            self.assertEqual(window.classification_columns, 4)
            self.assertEqual(window.classification_columns_combo.currentData(), 4)

    def test_xml_pair_mode_button_defaults_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )

            window = self._workbench(config_path)
            window.close()

            self.assertIsInstance(window.xml_pair_button, QCheckBox)
            self.assertEqual(window.xml_pair_button.text(), "LinkXML")
            self.assertIn("matching .xml labels", window.xml_pair_button.toolTip())
            self.assertFalse(window.xml_pair_button.isChecked())
            self.assertFalse(window.move_xml_pairs)

    def test_xml_pair_mode_toggle_updates_current_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            window, _source = self._loaded_workbench(tmp, names=("a.jpg",))

            self.assertFalse(window.move_xml_pairs)
            self.assertFalse(window.session.move_xml_pairs)

            window.xml_pair_button.click()

            self.assertTrue(window.move_xml_pairs)
            self.assertTrue(window.session.move_xml_pairs)
            self.assertEqual(window.xml_pair_button.text(), "LinkXML")
            self.assertTrue(window.xml_pair_button.isChecked())

            window.xml_pair_button.click()

            self.assertFalse(window.move_xml_pairs)
            self.assertFalse(window.session.move_xml_pairs)
            self.assertEqual(window.xml_pair_button.text(), "LinkXML")
            self.assertFalse(window.xml_pair_button.isChecked())
            window.close()

    def test_xml_pair_mode_programmatic_check_updates_current_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            window, _source = self._loaded_workbench(tmp, names=("a.jpg",))

            window.xml_pair_button.setChecked(True)

            self.assertTrue(window.move_xml_pairs)
            self.assertTrue(window.session.move_xml_pairs)
            self.assertEqual(window.xml_pair_button.text(), "LinkXML")
            self.assertTrue(window.xml_pair_button.isChecked())

            window.xml_pair_button.setChecked(False)

            self.assertFalse(window.move_xml_pairs)
            self.assertFalse(window.session.move_xml_pairs)
            self.assertEqual(window.xml_pair_button.text(), "LinkXML")
            self.assertFalse(window.xml_pair_button.isChecked())
            window.close()

    def test_xml_pair_mode_toggle_persists_to_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)

            window.xml_pair_button.click()
            window.close()

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertTrue(saved["image_classifier"]["move_xml_pairs"])

    def test_xml_pair_mode_restores_persisted_enabled_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                    "move_xml_pairs": True,
                },
            )
            window = self._workbench(config_path)
            window.close()

            self.assertTrue(window.move_xml_pairs)
            self.assertTrue(window.xml_pair_button.isChecked())
            self.assertEqual(window.xml_pair_button.text(), "LinkXML")

    def test_xml_pair_mode_persists_when_other_settings_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                    "move_xml_pairs": True,
                },
            )
            window = self._workbench(config_path)

            window.classification_columns_combo.setCurrentIndex(
                window.classification_columns_combo.findData(2)
            )
            window.close()

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertTrue(saved["image_classifier"]["move_xml_pairs"])
            self.assertEqual(saved["image_classifier"]["classification_columns"], 2)

    def test_new_session_inherits_xml_pair_mode_button_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            source.mkdir()
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)

            window.xml_pair_button.click()
            window.source_folder = source
            window.target_folder = root / "classified"
            window._create_session()
            window.close()

            self.assertTrue(window.session.move_xml_pairs)

    def test_presentation_mode_hides_xml_pair_button(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)
            window.show()
            self.app.processEvents()

            self.assertTrue(window.xml_pair_button.isVisible())

            window._toggle_presentation_mode(True)
            self.assertFalse(window.xml_pair_button.isVisible())

            window._toggle_presentation_mode(False)
            self.assertTrue(window.xml_pair_button.isVisible())
            window.close()

    def test_navigation_does_not_rebuild_large_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            source.mkdir()
            for name in ["a.jpg", "b.jpg", "c.jpg"]:
                (source / name).write_bytes(b"x")
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)
            window.source_folder = source
            window.target_folder = root / "classified"
            window._create_session()
            window.session.refresh()
            window.batch_total_count = len(window.session.images)
            window._sync_after_session_change("loaded")
            first_item = window.queue_list.item(0)

            window.next_image()
            window.close()

            self.assertIs(window.queue_list.item(0), first_item)

    def test_classify_returns_before_slow_move_finishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            source.mkdir()
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)
            window.session = _SlowSession(source)
            window.batch_total_count = 2

            started = time.perf_counter()
            window.classify("p")
            elapsed = time.perf_counter() - started
            completed = self._process_events_until(
                lambda: len(window.session.images) == 1
            )
            window.close()

            self.assertLess(elapsed, 0.1)
            self.assertTrue(completed)

    def test_xml_pair_mode_button_disabled_during_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            source.mkdir()
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)
            window.session = _SlowSession(source)
            window.batch_total_count = 2

            window.classify("p")
            try:
                self.assertFalse(window.xml_pair_button.isEnabled())
                completed = self._process_events_until(
                    lambda: not window._move_in_progress
                )

                self.assertTrue(completed)
                self.assertTrue(window.xml_pair_button.isEnabled())
            finally:
                self._process_events_until(lambda: not window._move_in_progress)
                window.close()

    def test_xml_pair_mode_button_disabled_during_undo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            source.mkdir()
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)
            session = _SlowSession(source)
            session.history.append(
                MoveRecord(
                    source=source / "a.jpg",
                    target=root / "classified" / "PT" / "a.jpg",
                    key="p",
                    category="PT",
                )
            )
            window.session = session
            window.batch_total_count = 2

            window.undo_last_action()
            try:
                self.assertFalse(window.xml_pair_button.isEnabled())
                completed = self._process_events_until(
                    lambda: not window._move_in_progress
                )

                self.assertTrue(completed)
                self.assertTrue(window.xml_pair_button.isEnabled())
            finally:
                self._process_events_until(lambda: not window._move_in_progress)
                window.close()

    def test_jump_to_image_selects_requested_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            source.mkdir()
            for name in ["a.jpg", "b.jpg", "c.jpg"]:
                (source / name).write_bytes(b"x")
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)
            window.source_folder = source
            window.target_folder = root / "classified"
            window._create_session()
            window.session.refresh()
            window.batch_total_count = len(window.session.images)
            window._sync_after_session_change("loaded")

            window.jump_spinbox.setValue(2)
            window.jump_to_image()
            window.close()

            self.assertEqual(window.session.current_index, 1)
            self.assertEqual(window.image_viewer.loaded[-1], source / "b.jpg")

    def test_preserve_zoom_toggle_updates_viewer(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)

            window.preserve_zoom_button.click()
            window.preserve_zoom_button.click()
            window.close()

            self.assertEqual(window.image_viewer.preserve_view_values, [True, False])

    def test_open_folder_action_uses_current_source_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            source.mkdir()
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {"open_folder": {"keys": ["Control-o"]}},
                },
            )
            window = self._workbench(config_path)
            launched = []
            window._folder_launcher = launched.append
            window.source_folder = source

            window.open_current_folder()
            window.close()

            self.assertEqual(launched, [source])
            self.assertIn(("Ctrl+O", "open_folder"), window._shortcut_registry)

    def test_session_defaults_target_to_source_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            source.mkdir()
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)
            window.source_folder = source

            window._create_session()
            window.close()

            self.assertEqual(window.target_folder, source)
            self.assertEqual(window.session.target_folder, source)

    def test_target_follows_source_until_manually_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_source = root / "first"
            second_source = root / "second"
            first_source.mkdir()
            second_source.mkdir()
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)

            with patch(
                "qt_workbench.QFileDialog.getExistingDirectory",
                side_effect=[str(first_source), str(second_source)],
            ):
                window.select_source_folder()
                window.select_source_folder()

            window.close()

            self.assertEqual(window.source_folder, second_source)
            self.assertEqual(window.target_folder, second_source)
            self.assertEqual(window.session.target_folder, second_source)
            self.assertEqual(window.target_path_label.toolTip(), str(second_source))

    def test_manual_target_is_kept_when_source_changes_later(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_source = root / "first"
            second_source = root / "second"
            manual_target = root / "manual-target"
            first_source.mkdir()
            second_source.mkdir()
            manual_target.mkdir()
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)

            with patch(
                "qt_workbench.QFileDialog.getExistingDirectory",
                side_effect=[
                    str(first_source),
                    str(manual_target),
                    str(second_source),
                ],
            ):
                window.select_source_folder()
                window.select_target_folder()
                window.select_source_folder()

            window.close()

            self.assertEqual(window.source_folder, second_source)
            self.assertEqual(window.target_folder, manual_target)
            self.assertEqual(window.session.target_folder, manual_target)
            self.assertEqual(window.target_path_label.toolTip(), str(manual_target))

    def test_active_profile_bindings_can_be_updated_and_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)

            window.update_active_bindings({"x": "XR"})
            window.close()

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            image_config = saved["image_classifier"]
            self.assertEqual(image_config["binding_profiles"]["default"], {"x": "XR"})
            self.assertEqual(image_config["default_key_bindings"], {"x": "XR"})
            self.assertIn(("X", "classify:x"), window._shortcut_registry)

    def test_create_profile_copies_current_bindings_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)

            created = window.create_binding_profile("review")
            window.close()

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            image_config = saved["image_classifier"]
            self.assertTrue(created)
            self.assertEqual(image_config["active_binding_profile"], "review")
            self.assertEqual(image_config["binding_profiles"]["review"], {"p": "PT"})

    def test_delete_active_profile_switches_to_default_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"x": "XR"},
                    "binding_profiles": {
                        "default": {"p": "PT"},
                        "review": {"x": "XR"},
                    },
                    "active_binding_profile": "review",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)

            deleted = window.delete_binding_profile(confirm=False)
            window.close()

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            image_config = saved["image_classifier"]
            self.assertTrue(deleted)
            self.assertNotIn("review", image_config["binding_profiles"])
            self.assertEqual(image_config["active_binding_profile"], "default")
            self.assertEqual(image_config["default_key_bindings"], {"p": "PT"})

    def test_controls_are_grouped_by_workflow_area(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)

            self.assertEqual(window.jump_spinbox.parent(), window.viewer_toolbar)
            self.assertEqual(window.preserve_zoom_button.parent(), window.viewer_toolbar)
            self.assertEqual(window.profile_combo.parent(), window.profile_panel)
            self.assertEqual(window.edit_bindings_button.parent(), window.profile_panel)
            self.assertEqual(window.new_profile_button.parent(), window.profile_panel)
            self.assertEqual(window.delete_profile_button.parent(), window.profile_panel)
            self.assertEqual(window.refresh_button.parent(), window.top_bar)
            self.assertEqual(window.open_folder_button.parent(), window.top_bar)
            self.assertEqual(window.queue_search_input.parent(), window.queue_panel)
            self.assertEqual(window.queue_find_button.parent(), window.queue_panel)
            self.assertEqual(window.queue_back_button.parent(), window.queue_panel)
            self.assertEqual(window.queue_search_input.placeholderText(), "Filename")
            self.assertEqual(window.queue_find_button.text(), "")
            self.assertEqual(window.queue_find_button.accessibleName(), "Find")
            self.assertEqual(window.queue_find_button.toolTip(), "Find filename")
            self.assertFalse(window.queue_find_button.icon().isNull())
            self.assertEqual(window.queue_back_button.text(), "Back")
            self.assertEqual(window.queue_back_button.toolTip(), "Back to previous image")
            self.assertFalse(window.queue_back_button.icon().isNull())
            self.assertEqual(
                window.queue_count_label.minimumHeight(),
                window.queue_back_button.minimumHeight(),
            )
            self.assertTrue(
                window.queue_count_label.alignment()
                & Qt.AlignmentFlag.AlignVCenter
            )
            self.assertLess(
                window.queue_find_button.maximumWidth(),
                window.queue_back_button.maximumWidth(),
            )
            self.assertEqual(
                window.queue_find_button.minimumHeight(),
                window.queue_back_button.minimumHeight(),
            )
            window.close()

    def test_queue_filename_search_jumps_to_exact_case_insensitive_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            window, source = self._loaded_workbench(tmp)

            window.queue_search_input.setText("b.jpg")
            window.search_queue_filename()
            window.close()

            self.assertEqual(window.session.current_index, 1)
            self.assertEqual(window.image_viewer.loaded[-1], source / "B.JPG")
            self.assertEqual(window.queue_list.currentRow(), 1)
            self.assertEqual(window.jump_spinbox.value(), 2)

    def test_queue_filename_search_button_jumps_by_stem_across_supported_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            window, source = self._loaded_workbench(tmp)

            window.queue_search_input.setText("c")
            window.queue_find_button.click()
            window.close()

            self.assertEqual(window.session.current_index, 2)
            self.assertEqual(window.image_viewer.loaded[-1], source / "c.png")
            self.assertEqual(window.queue_list.currentRow(), 2)

    def test_queue_filename_search_jumps_from_stem_to_jpg_named_ss(self):
        with tempfile.TemporaryDirectory() as tmp:
            window, source = self._loaded_workbench(
                tmp,
                names=("a.jpg", "ss.jpg", "z.png"),
            )

            window.queue_search_input.setText("ss")
            window.search_queue_filename()
            window.close()

            self.assertEqual(window.session.current_index, 1)
            self.assertEqual(window.image_viewer.loaded[-1], source / "ss.jpg")
            self.assertEqual(window.queue_list.currentRow(), 1)

    def test_queue_filename_search_enter_jumps_by_stem(self):
        with tempfile.TemporaryDirectory() as tmp:
            window, source = self._loaded_workbench(tmp)

            window.queue_search_input.setText("c")
            window.queue_search_input.returnPressed.emit()
            window.close()

            self.assertEqual(window.session.current_index, 2)
            self.assertEqual(window.image_viewer.loaded[-1], source / "c.png")

    def test_queue_filename_search_keeps_position_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            window, source = self._loaded_workbench(tmp)

            window.queue_search_input.setText("missing.jpg")
            window.search_queue_filename()
            message = window.statusBar().currentMessage()
            window.close()

            self.assertEqual(window.session.current_index, 0)
            self.assertEqual(window.image_viewer.loaded[-1], source / "a.jpg")
            self.assertIn("not found", message.casefold())

    def test_back_returns_to_previous_image_after_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            window, source = self._loaded_workbench(tmp)

            window.queue_search_input.setText("c.png")
            window.search_queue_filename()
            window.back_to_previous_image()
            window.close()

            self.assertEqual(window.session.current_index, 0)
            self.assertEqual(window.image_viewer.loaded[-1], source / "a.jpg")

    def test_back_returns_to_previous_image_after_queue_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            window, source = self._loaded_workbench(tmp)

            item = window.queue_list.item(2)
            window._handle_queue_item_clicked(item)
            window.back_to_previous_image()
            window.close()

            self.assertEqual(window.session.current_index, 0)
            self.assertEqual(window.image_viewer.loaded[-1], source / "a.jpg")

    def test_back_returns_to_previous_image_after_jump(self):
        with tempfile.TemporaryDirectory() as tmp:
            window, source = self._loaded_workbench(tmp)

            window.jump_spinbox.setValue(3)
            window.jump_to_image()
            window.back_to_previous_image()
            window.close()

            self.assertEqual(window.session.current_index, 0)
            self.assertEqual(window.image_viewer.loaded[-1], source / "a.jpg")

    def test_back_tracks_next_previous_and_skip_navigation(self):
        with tempfile.TemporaryDirectory() as tmp:
            window, source = self._loaded_workbench(tmp)

            window.next_image()
            window.back_to_previous_image()
            self.assertEqual(window.session.current_index, 0)

            window.next_image()
            window.next_image()
            window.previous_image()
            window.back_to_previous_image()
            self.assertEqual(window.session.current_index, 2)

            window.skip_image()
            window.back_to_previous_image()
            window.close()

            self.assertEqual(window.session.current_index, 1)
            self.assertEqual(window.image_viewer.loaded[-1], source / "B.JPG")

    def test_back_history_keeps_latest_five_positions(self):
        with tempfile.TemporaryDirectory() as tmp:
            window, source = self._loaded_workbench(
                tmp,
                names=("a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg", "f.jpg", "g.jpg"),
            )

            for index in range(1, 7):
                window.jump_spinbox.setValue(index + 1)
                window.jump_to_image()

            self.assertEqual(
                window._previous_image_paths,
                [
                    source / "b.jpg",
                    source / "c.jpg",
                    source / "d.jpg",
                    source / "e.jpg",
                    source / "f.jpg",
                ],
            )

            for expected_index in [5, 4, 3, 2, 1]:
                window.back_to_previous_image()
                self.assertEqual(window.session.current_index, expected_index)

            window.back_to_previous_image()
            message = window.statusBar().currentMessage()
            window.close()

            self.assertEqual(window.session.current_index, 1)
            self.assertIn("no previous", message.casefold())

    def test_new_session_clears_back_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            window, _source = self._loaded_workbench(tmp)

            window.next_image()
            self.assertTrue(window._previous_image_paths)

            second_source = Path(tmp) / "next-batch"
            second_source.mkdir()
            (second_source / "fresh.jpg").write_bytes(b"x")
            window.source_folder = second_source
            window.target_folder = second_source
            window._create_session()
            window.close()

            self.assertEqual(window._previous_image_paths, [])

    def test_back_reports_unavailable_when_previous_image_left_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            window, _source = self._loaded_workbench(tmp)

            window.next_image()
            stale_path = window._previous_image_paths[-1]
            window.session.images = [
                path for path in window.session.images if path != stale_path
            ]
            window.back_to_previous_image()
            message = window.statusBar().currentMessage()
            window.close()

            self.assertEqual(window.session.current_index, 1)
            self.assertEqual(window._previous_image_paths, [])
            self.assertIn("no longer available", message.casefold())

    def test_viewer_zoom_can_exceed_fit_and_survives_resize(self):
        viewer = ImageViewer()
        viewer.resize(800, 600)
        viewer.show()
        self.app.processEvents()
        image = QImage(240, 160, QImage.Format.Format_RGB32)
        image.fill(QColor("#c84f44"))

        viewer._handle_image_loaded(Path("sample.jpg"), viewer._load_token, image, "")
        self.app.processEvents()
        fit_scale = viewer.transform().m11()

        viewer.zoom_by(2.0)
        zoomed_scale = viewer.transform().m11()
        viewer.resize(820, 600)
        self.app.processEvents()
        resized_scale = viewer.transform().m11()
        viewer.close()
        viewer.deleteLater()
        self.app.processEvents()

        self.assertGreater(zoomed_scale, fit_scale)
        self.assertAlmostEqual(resized_scale, zoomed_scale, places=4)

    def test_viewer_wheel_without_ctrl_requests_navigation(self):
        viewer = ImageViewer()
        viewer.resize(800, 600)
        viewer.show()
        self.app.processEvents()
        image = QImage(240, 160, QImage.Format.Format_RGB32)
        image.fill(QColor("#4f7fc8"))
        viewer._handle_image_loaded(Path("sample.jpg"), viewer._load_token, image, "")
        self.app.processEvents()
        fit_scale = viewer.transform().m11()
        navigation = []
        signal = getattr(viewer, "wheel_navigation_requested", None)
        self.assertIsNotNone(signal)
        signal.connect(navigation.append)

        up_event = self._wheel_event(120)
        down_event = self._wheel_event(-120)
        viewer.wheelEvent(up_event)
        viewer.wheelEvent(down_event)
        self.app.processEvents()
        final_scale = viewer.transform().m11()
        viewer.close()
        viewer.deleteLater()
        self.app.processEvents()

        self.assertEqual(navigation, [-1, 1])
        self.assertAlmostEqual(final_scale, fit_scale, places=4)
        self.assertTrue(up_event.isAccepted())
        self.assertTrue(down_event.isAccepted())

    def test_viewer_ctrl_wheel_zooms_without_navigation(self):
        viewer = ImageViewer()
        viewer.resize(800, 600)
        viewer.show()
        self.app.processEvents()
        image = QImage(240, 160, QImage.Format.Format_RGB32)
        image.fill(QColor("#4f7fc8"))
        viewer._handle_image_loaded(Path("sample.jpg"), viewer._load_token, image, "")
        self.app.processEvents()
        fit_scale = viewer.transform().m11()
        navigation = []
        signal = getattr(viewer, "wheel_navigation_requested", None)
        self.assertIsNotNone(signal)
        signal.connect(navigation.append)

        event = self._wheel_event(120, Qt.KeyboardModifier.ControlModifier)
        viewer.wheelEvent(event)
        self.app.processEvents()
        zoomed_scale = viewer.transform().m11()
        viewer.close()
        viewer.deleteLater()
        self.app.processEvents()

        self.assertEqual(navigation, [])
        self.assertGreater(zoomed_scale, fit_scale)
        self.assertTrue(event.isAccepted())

    def test_viewer_wheel_navigation_signal_drives_workbench_navigation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            source.mkdir()
            for name in ("a.jpg", "b.jpg", "c.jpg"):
                (source / name).write_bytes(b"x")
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = AnnotationWorkbench(ConfigManager(str(config_path)))
            window.source_folder = source
            window.target_folder = root / "classified"
            window._create_session()
            window.session.refresh()
            window.batch_total_count = len(window.session.images)
            window._sync_after_session_change("loaded")

            signal = getattr(window.image_viewer, "wheel_navigation_requested", None)
            self.assertIsNotNone(signal)
            signal.emit(1)
            next_index = window.session.current_index
            signal.emit(-1)
            previous_index = window.session.current_index
            window.close()

            self.assertEqual(next_index, 1)
            self.assertEqual(previous_index, 0)

    def test_viewer_keeps_smooth_pixmap_item_at_high_zoom_and_fit(self):
        viewer = ImageViewer()
        viewer.resize(800, 600)
        viewer.show()
        self.app.processEvents()
        image = QImage(240, 160, QImage.Format.Format_RGB32)
        image.fill(QColor("#4f7fc8"))

        viewer._handle_image_loaded(Path("sample.jpg"), viewer._load_token, image, "")
        self.app.processEvents()

        self.assertEqual(
            viewer._pixmap_item.transformationMode(),
            Qt.TransformationMode.SmoothTransformation,
        )
        self.assertTrue(
            bool(viewer.renderHints() & QPainter.RenderHint.SmoothPixmapTransform)
        )

        viewer.zoom_by(2.0)
        viewer._finish_zoom_interaction()
        self.assertEqual(
            viewer._pixmap_item.transformationMode(),
            Qt.TransformationMode.SmoothTransformation,
        )
        self.assertTrue(
            bool(viewer.renderHints() & QPainter.RenderHint.SmoothPixmapTransform)
        )

        viewer.fit_to_window()
        self.assertEqual(
            viewer._pixmap_item.transformationMode(),
            Qt.TransformationMode.SmoothTransformation,
        )
        viewer.close()
        viewer.deleteLater()
        self.app.processEvents()

    def test_viewer_coalesces_rapid_load_requests_to_latest_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            colors = ("#a14242", "#42a16a", "#426aa1")
            for index, color in enumerate(colors):
                path = Path(tmp) / f"image-{index}.bmp"
                image = QImage(80, 60, QImage.Format.Format_RGB32)
                image.fill(QColor(color))
                self.assertTrue(image.save(str(path), "BMP"))
                paths.append(path)

            gate = threading.Event()
            started = threading.Event()
            original_run = _ImageLoadWorker.run

            @Slot()
            def blocked_run(worker):
                started.set()
                gate.wait(2.0)
                original_run(worker)

            viewer = ImageViewer()
            try:
                with patch("qt_image_viewer._ImageLoadWorker.run", blocked_run):
                    viewer.load_image(paths[0])
                    self.assertTrue(
                        self._process_events_until(started.is_set, timeout=1.0)
                    )
                    viewer.load_image(paths[1])
                    viewer.load_image(paths[2])

                    self.assertEqual(len(viewer._active_threads), 1)
                    self.assertEqual(
                        viewer._pending_load,
                        (paths[2], viewer._load_token),
                    )

                    gate.set()
                    loaded = self._process_events_until(
                        lambda: not viewer._active_threads
                        and viewer._loading_path is None,
                        timeout=3.0,
                    )

                self.assertTrue(loaded)
                self.assertEqual(
                    viewer._source_image.pixelColor(0, 0),
                    QColor(colors[-1]),
                )
            finally:
                gate.set()
                viewer.shutdown(3000)
                viewer.close()
                viewer.deleteLater()
                self.app.processEvents()

    def test_viewer_does_not_schedule_old_image_hq_while_new_image_loads(self):
        viewer = ImageViewer()
        viewer.resize(400, 300)
        viewer.show()
        self.app.processEvents()
        old_image = QImage(2000, 1000, QImage.Format.Format_RGB32)
        old_image.fill(QColor("#a14242"))
        viewer._handle_image_loaded(Path("old.jpg"), viewer._load_token, old_image, "")
        viewer._zoom_quality_timer.stop()
        viewer._loading_path = Path("next.jpg")

        try:
            viewer.zoom_by(1.25)

            self.assertFalse(viewer._zoom_quality_timer.isActive())
            viewer._finish_zoom_interaction()
            self.assertEqual(viewer._hq_threads, {})
        finally:
            viewer._loading_path = None
            viewer.shutdown(3000)
            viewer.close()
            viewer.deleteLater()
            self.app.processEvents()

    def test_hq_worker_cancellation_does_not_wrap_current_qthread(self):
        source = QImage(80, 60, QImage.Format.Format_RGB32)
        source.fill(QColor("#426aa1"))
        worker = _HqResizeWorker(7, source, 40, 30, source.width())
        results = []
        worker.finished.connect(lambda *args: results.append(args))

        class ForbiddenQThread:
            @staticmethod
            def currentThread():
                raise AssertionError("HQ cancellation must not wrap the current QThread")

        self.assertTrue(
            hasattr(worker, "cancel"),
            "HQ worker must expose a cancellation API that avoids QThread wrappers",
        )
        worker.cancel()
        with patch("qt_image_viewer.QThread", ForbiddenQThread):
            worker.run()

        self.assertEqual(len(results), 1)
        token, image, display_scale, error = results[0]
        self.assertEqual(token, 7)
        self.assertTrue(image.isNull())
        self.assertEqual(display_scale, 1.0)
        self.assertEqual(error, "cancelled")

    def test_hq_worker_cancellation_after_resize_avoids_current_qthread(self):
        source = QImage(80, 60, QImage.Format.Format_RGB32)
        source.fill(QColor("#426aa1"))
        worker = _HqResizeWorker(8, source, 40, 30, source.width())
        results = []
        resize_started = threading.Event()
        resize_gate = threading.Event()

        def blocked_resize(_source, width, height):
            resize_started.set()
            resize_gate.wait(2.0)
            image = QImage(width, height, QImage.Format.Format_RGB32)
            image.fill(QColor("#426aa1"))
            return image

        class ForbiddenQThread:
            @staticmethod
            def currentThread():
                raise AssertionError("HQ cancellation must not wrap the current QThread")

        worker.finished.connect(lambda *args: results.append(args))
        with (
            patch("qt_image_viewer.QThread", ForbiddenQThread),
            patch("qt_image_viewer._lanczos_resize", blocked_resize),
        ):
            runner = threading.Thread(target=worker.run)
            runner.start()
            self.assertTrue(resize_started.wait(1.0))
            worker.cancel()
            resize_gate.set()
            runner.join(3.0)

        self.assertFalse(runner.is_alive())
        self.assertTrue(
            self._process_events_until(lambda: len(results) == 1, timeout=1.0)
        )
        self.assertEqual(len(results), 1)
        token, image, display_scale, error = results[0]
        self.assertEqual(token, 8)
        self.assertTrue(image.isNull())
        self.assertEqual(display_scale, 1.0)
        self.assertEqual(error, "cancelled")

    def test_viewer_abort_hq_cancels_the_active_worker(self):
        viewer = ImageViewer()
        viewer.resize(400, 300)
        viewer.show()
        self.app.processEvents()
        source = QImage(2000, 1000, QImage.Format.Format_RGB32)
        source.fill(QColor("#426aa1"))
        viewer._handle_image_loaded(Path("big.jpg"), viewer._load_token, source, "")
        viewer._zoom_quality_timer.stop()
        resize_started = threading.Event()
        resize_gate = threading.Event()

        def blocked_resize(_source, width, height):
            resize_started.set()
            resize_gate.wait(2.0)
            image = QImage(width, height, QImage.Format.Format_RGB32)
            image.fill(QColor("#426aa1"))
            return image

        try:
            with patch("qt_image_viewer._lanczos_resize", blocked_resize):
                viewer._finish_zoom_interaction()
                self.assertTrue(
                    self._process_events_until(resize_started.is_set, timeout=1.0)
                )
                thread, worker = next(iter(viewer._hq_threads.values()))

                viewer._abort_hq()

                self.assertTrue(worker._cancel_requested.is_set())
                self.assertFalse(thread.isInterruptionRequested())
                resize_gate.set()

                # Wait for cleanup. With QueuedConnection, _cleanup_hq_thread_early
                # is queued. _prune_hq_threads provides immediate cleanup for finished threads.
                def check_and_prune():
                    # Trigger defensive cleanup in _prune_hq_threads
                    if viewer._hq_threads:
                        viewer._abort_hq()
                    return not viewer._hq_threads

                self.assertTrue(
                    self._process_events_until(check_and_prune, timeout=3.0)
                )
        finally:
            resize_gate.set()
            viewer.shutdown(3000)
            viewer.close()
            viewer.deleteLater()
            self.app.processEvents()

    def test_viewer_real_lanczos_cancel_stress(self):
        child_script = textwrap.dedent(
            """
            import sys
            import threading
            import time
            from pathlib import Path

            from PySide6.QtGui import QColor, QImage
            from PySide6.QtWidgets import QApplication

            import qt_image_viewer as viewer_module


            def process_until(app, predicate, timeout, label):
                deadline = time.perf_counter() + timeout
                while time.perf_counter() < deadline:
                    app.processEvents()
                    if predicate():
                        return
                    time.sleep(0.001)
                raise TimeoutError(label)


            image_path = Path(sys.argv[1])
            source = QImage(3200, 2400, QImage.Format.Format_RGB32)
            source.fill(QColor("#426aa1"))
            if not source.save(str(image_path), "JPG"):
                raise RuntimeError("unable to create stress image")

            entered_lanczos = threading.Event()
            original_resize = viewer_module._lanczos_resize

            def observed_resize(*args):
                entered_lanczos.set()
                return original_resize(*args)

            viewer_module._lanczos_resize = observed_resize
            app = QApplication([])
            viewer = viewer_module.ImageViewer()
            viewer.resize(1000, 700)
            viewer.show()
            app.processEvents()

            try:
                for attempt in range(6):
                    entered_lanczos.clear()
                    viewer.load_image(image_path)
                    process_until(
                        app,
                        lambda: not viewer._active_threads
                        and viewer._loading_path is None,
                        5.0,
                        f"initial load {attempt}",
                    )
                    process_until(
                        app,
                        entered_lanczos.is_set,
                        5.0,
                        f"HQ start {attempt}",
                    )

                    viewer.load_image(image_path)
                    process_until(
                        app,
                        lambda: not viewer._active_threads
                        and viewer._loading_path is None,
                        5.0,
                        f"replacement load {attempt}",
                    )
                    viewer._zoom_quality_timer.stop()
                    process_until(
                        app,
                        lambda: not viewer._hq_threads,
                        5.0,
                        f"HQ drain {attempt}",
                    )
            finally:
                viewer.shutdown(5000)
                viewer.close()
                viewer.deleteLater()
                app.processEvents()

            print("stress-ok")
            """
        )

        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "hq-stress.jpg"
            env = os.environ.copy()
            env["QT_QPA_PLATFORM"] = "offscreen"
            result = subprocess.run(
                [sys.executable, "-c", child_script, str(image_path)],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )

        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        self.assertIn("stress-ok", result.stdout)

    def test_viewer_shutdown_waits_for_running_image_worker(self):
        """Shutdown with a worker stuck in file I/O: bounded wait, then clean exit.

        The gate lives at the Path.read_bytes level, NOT by overriding run --
        overriding run (the old flaky approach) makes PySide6 deliver the
        started->run call on the MAIN thread, so the test never exercised
        worker-thread behavior. With an unmodified @Slot run, the worker
        genuinely blocks inside the worker thread.
        """
        entered = threading.Event()
        gate = threading.Event()
        io_threads = []

        class _GatedPath(type(Path())):
            def read_bytes(self):
                io_threads.append(threading.current_thread().name)
                entered.set()
                gate.wait(3.0)
                return super().read_bytes()

        class _GatedLoadWorker(_ImageLoadWorker):
            # Override the path, never run(): run must stay the base @Slot
            # method so the queued started->run call lands in the worker thread.
            def __init__(self, path, token):
                super().__init__(path, token)
                self._path = _GatedPath(self._path)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "slow.bmp"
            image = QImage(80, 60, QImage.Format.Format_RGB32)
            image.fill(QColor("#426aa1"))
            self.assertTrue(image.save(str(path), "BMP"))

            viewer = ImageViewer()
            thread = None
            try:
                with patch("qt_image_viewer._ImageLoadWorker", _GatedLoadWorker):
                    viewer.load_image(path)
                    self.assertTrue(
                        self._process_events_until(entered.is_set, timeout=1.0)
                    )
                    # The gate must actually hold the WORKER thread, not main.
                    self.assertNotIn("MainThread", io_threads)
                    thread = next(iter(viewer._active_threads.values()))[0]
                    shutdown_started = time.monotonic()
                    viewer.shutdown(timeout_ms=50)
                    elapsed = time.monotonic() - shutdown_started
                    # Bounded wait: returns without waiting for the gated worker.
                    self.assertLess(elapsed, 1.0)
                    # Dict is cleared regardless of the still-running thread.
                    self.assertEqual(viewer._active_threads, {})
                # Open the gate; the worker finishes and the thread exits.
                gate.set()

                def _thread_done():
                    try:
                        return not thread.isRunning()
                    except RuntimeError:
                        # C++ object already deleted by thread.finished ->
                        # deleteLater: the cleanup chain ran to completion.
                        return True

                self.assertTrue(
                    self._process_events_until(_thread_done, timeout=3.0)
                )
            finally:
                gate.set()
                if thread is not None:
                    try:
                        thread.wait(3000)
                    except RuntimeError:
                        pass  # C++ object already deleted: cleanup completed
                viewer.close()
                viewer.deleteLater()
                self.app.processEvents()

    def test_shutdown_bounded_wait_on_stuck_hq_worker(self):
        """Shutdown must return promptly when an HQ resize is stuck mid-flight.

        Cancellation is cooperative (checked before/after _lanczos_resize), so
        a resize blocked on a gate cannot be interrupted. shutdown() must use
        a bounded wait and return without raising, leaving the thread to
        finish on its own.
        """
        from qt_image_viewer import _lanczos_resize

        gate = threading.Event()
        resize_entered = threading.Event()

        def gated_resize(source, width, height):
            resize_entered.set()
            gate.wait(3.0)
            return source

        viewer = ImageViewer()
        image = QImage(2000, 1000, QImage.Format.Format_RGB32)
        image.fill(QColor("#314f6e"))
        viewer._handle_image_loaded(Path("big.jpg"), viewer._load_token, image, "")
        self.app.processEvents()
        thread = None

        try:
            with patch("qt_image_viewer._lanczos_resize", gated_resize):
                viewer._finish_zoom_interaction()
                self.assertTrue(
                    self._process_events_until(
                        resize_entered.is_set, timeout=3.0
                    )
                )
                self.assertTrue(viewer._hq_threads)
                thread = next(iter(viewer._hq_threads.values()))[0]
                shutdown_started = time.monotonic()
                viewer.shutdown(timeout_ms=50)
                elapsed = time.monotonic() - shutdown_started
                self.assertLess(elapsed, 1.0)
                self.assertEqual(viewer._hq_threads, {})
                self.assertIsNone(viewer._hq_active_token)
        finally:
            gate.set()
            # Let the stuck thread finish so it is not destroyed while running.
            if thread is not None:
                try:
                    thread.wait(3000)
                except RuntimeError:
                    pass  # C++ object already deleted: cleanup chain completed
            viewer.close()
            viewer.deleteLater()
            self.app.processEvents()

    def test_hq_failure_retries_with_backoff_then_gives_up(self):
        """A persistently failing HQ resize retries at most _HQ_RETRY_MAX times."""
        calls = []

        def failing_resize(source, width, height):
            calls.append((width, height))
            from PySide6.QtGui import QImage as QImg
            return QImg()  # null result -> "HQ resize failed" error path

        viewer = ImageViewer()
        viewer.resize(400, 300)
        viewer.show()
        self.app.processEvents()
        image = QImage(2000, 1000, QImage.Format.Format_RGB32)
        image.fill(QColor("#5c4f8f"))
        viewer._handle_image_loaded(Path("big.jpg"), viewer._load_token, image, "")
        self.app.processEvents()
        viewer._zoom_quality_timer.stop()

        try:
            with patch("qt_image_viewer._lanczos_resize", failing_resize):
                viewer._finish_zoom_interaction()
                # Drive retries to exhaustion (each retry fires the timer,
                # which re-enters _finish_zoom_interaction). Generous timeout:
                # backoff totals 140+280+560 = 980 ms plus slack.
                self.assertTrue(
                    self._process_events_until(
                        lambda: len(calls) >= 4, timeout=5.0
                    )
                )
                # Let any stray timers settle, then confirm no more retries.
                time.sleep(0.7)
                self.app.processEvents()
                final_calls = len(calls)
                time.sleep(0.7)
                self.app.processEvents()
                self.assertEqual(len(calls), final_calls)
            # Budget was consumed and reset after giving up.
            self.assertEqual(viewer._hq_retry_count, 0)
        finally:
            viewer.shutdown(500)
            viewer.close()
            viewer.deleteLater()
            self.app.processEvents()

    def test_viewer_retains_source_image_and_unit_display_scale_on_load(self):
        viewer = ImageViewer()
        viewer.resize(800, 600)
        viewer.show()
        self.app.processEvents()
        image = QImage(320, 200, QImage.Format.Format_RGB32)
        image.fill(QColor("#214f6e"))

        viewer._handle_image_loaded(Path("sample.jpg"), viewer._load_token, image, "")
        self.app.processEvents()

        self.assertFalse(viewer._source_image.isNull())
        self.assertEqual(viewer._source_image.width(), 320)
        self.assertEqual(viewer._source_image.height(), 200)
        self.assertAlmostEqual(viewer._display_scale, 1.0, places=6)
        self.assertEqual(viewer._pixmap_item.pixmap().width(), 320)
        viewer.close()
        viewer.deleteLater()
        self.app.processEvents()

    def test_viewer_clear_resets_source_image_and_display_scale(self):
        viewer = ImageViewer()
        image = QImage(40, 30, QImage.Format.Format_RGB32)
        image.fill(QColor("#000000"))
        viewer._handle_image_loaded(Path("sample.jpg"), viewer._load_token, image, "")
        viewer.clear("empty")
        self.assertTrue(viewer._source_image is None or viewer._source_image.isNull())
        self.assertAlmostEqual(viewer._display_scale, 1.0, places=6)
        viewer.close()
        viewer.deleteLater()
        self.app.processEvents()

    def test_viewer_idle_settle_replaces_pixmap_with_hq_resize(self):
        viewer = ImageViewer()
        viewer.resize(400, 300)
        viewer.show()
        self.app.processEvents()
        # Large source so fit scale < 1 and HQ target differs from source size.
        image = QImage(2000, 1000, QImage.Format.Format_RGB32)
        image.fill(QColor("#8aa9c1"))
        viewer._handle_image_loaded(Path("big.jpg"), viewer._load_token, image, "")
        self.app.processEvents()

        source_w = viewer._source_image.width()
        pre_w = viewer._pixmap_item.pixmap().width()
        self.assertEqual(pre_w, source_w)

        # Force settle without waiting on real wall clock.
        viewer._zoom_quality_timer.stop()
        viewer._finish_zoom_interaction()

        settled = self._process_events_until(
            lambda: viewer._pixmap_item.pixmap().width() != source_w
            and not viewer._hq_threads,
            timeout=3.0,
        )
        post_w = viewer._pixmap_item.pixmap().width()
        viewer.close()
        viewer.deleteLater()
        self.app.processEvents()

        self.assertTrue(settled)
        self.assertNotEqual(post_w, source_w)
        self.assertGreater(post_w, 0)

    def test_viewer_rezoom_cancels_stale_hq_and_restores_source_for_interaction(self):
        viewer = ImageViewer()
        viewer.resize(400, 300)
        viewer.show()
        self.app.processEvents()
        image = QImage(1800, 1200, QImage.Format.Format_RGB32)
        image.fill(QColor("#c18a8a"))
        viewer._handle_image_loaded(Path("big.jpg"), viewer._load_token, image, "")
        self.app.processEvents()

        viewer._finish_zoom_interaction()
        self._process_events_until(
            lambda: abs(viewer._display_scale - 1.0) > 1e-6 or not viewer._hq_threads,
            timeout=3.0,
        )

        # Next interactive zoom must return to source display scale for matrix zoom.
        before_token = viewer._hq_token
        viewer.zoom_by(1.25)
        self.assertEqual(viewer._pixmap_item.pixmap().width(), viewer._source_image.width())
        self.assertAlmostEqual(viewer._display_scale, 1.0, places=6)
        self.assertGreater(viewer._hq_token, before_token)

        viewer.close()
        viewer.deleteLater()
        self.app.processEvents()

    def test_viewer_hq_settle_preserves_effective_scale(self):
        viewer = ImageViewer()
        viewer.resize(500, 400)
        viewer.show()
        self.app.processEvents()
        image = QImage(1600, 900, QImage.Format.Format_RGB32)
        image.fill(QColor("#6e8f21"))
        viewer._handle_image_loaded(Path("big.jpg"), viewer._load_token, image, "")
        self.app.processEvents()

        viewer.zoom_by(1.5)
        effective_before = viewer.transform().m11() * viewer._display_scale

        viewer._finish_zoom_interaction()
        self._process_events_until(lambda: not viewer._hq_threads, timeout=3.0)
        # If HQ applied, display_scale may change; product must match.
        effective_after = viewer.transform().m11() * viewer._display_scale

        viewer.close()
        viewer.deleteLater()
        self.app.processEvents()

        self.assertAlmostEqual(effective_after, effective_before, places=3)

    def test_viewer_hq_settle_preserves_source_center_when_panned(self):
        """HQ swap must not re-anchor under mouse (reads as extra zoom/pan)."""
        viewer = ImageViewer()
        viewer.resize(800, 600)
        viewer.show()
        self.app.processEvents()
        image = QImage(3000, 2000, QImage.Format.Format_RGB32)
        image.fill(QColor("#a05050"))
        viewer._handle_image_loaded(Path("big.jpg"), viewer._load_token, image, "")
        self.app.processEvents()

        viewer.zoom_by(3.0)
        viewer.horizontalScrollBar().setValue(400)
        viewer.verticalScrollBar().setValue(300)
        self.app.processEvents()

        center = viewer.viewport().rect().center()
        scene_before = viewer.mapToScene(center)
        display_before = max(viewer._display_scale, 1e-6)
        src_before = (
            scene_before.x() / display_before,
            scene_before.y() / display_before,
        )
        effective_before = viewer.transform().m11() * viewer._display_scale

        viewer._finish_zoom_interaction()
        settled = self._process_events_until(
            lambda: abs(viewer._display_scale - 1.0) > 1e-6 or not viewer._hq_threads,
            timeout=3.0,
        )
        self.assertTrue(settled)

        scene_after = viewer.mapToScene(center)
        display_after = max(viewer._display_scale, 1e-6)
        src_after = (scene_after.x() / display_after, scene_after.y() / display_after)
        effective_after = viewer.transform().m11() * viewer._display_scale

        viewer.close()
        viewer.deleteLater()
        self.app.processEvents()

        self.assertAlmostEqual(effective_after, effective_before, places=3)
        # Integer HQ pixel sizes introduce ~1 source-pixel rounding; the old
        # AnchorUnderMouse path jumped by hundreds of source pixels.
        self.assertLess(abs(src_after[0] - src_before[0]), 3.0)
        self.assertLess(abs(src_after[1] - src_before[1]), 3.0)

    def test_viewer_preserve_view_keeps_effective_scale_across_images(self):
        viewer = ImageViewer()
        viewer.resize(800, 600)
        viewer.show()
        self.app.processEvents()
        viewer.set_preserve_view(True)

        image1 = QImage(2500, 1500, QImage.Format.Format_RGB32)
        image1.fill(QColor("#214f6e"))
        viewer._handle_image_loaded(Path("one.jpg"), viewer._load_token, image1, "")
        self.app.processEvents()
        viewer.zoom_by(2.0)
        viewer._finish_zoom_interaction()
        self._process_events_until(lambda: not viewer._hq_threads, timeout=3.0)
        effective_kept = viewer.transform().m11() * viewer._display_scale

        image2 = QImage(2500, 1500, QImage.Format.Format_RGB32)
        image2.fill(QColor("#6e214f"))
        viewer._handle_image_loaded(Path("two.jpg"), viewer._load_token, image2, "")
        self.app.processEvents()
        effective_after = viewer.transform().m11() * viewer._display_scale

        viewer.close()
        viewer.deleteLater()
        self.app.processEvents()

        self.assertAlmostEqual(effective_after, effective_kept, places=3)
        self.assertAlmostEqual(viewer._display_scale, 1.0, places=6)

    def test_viewer_skips_hq_when_effective_scale_at_or_above_one(self):
        viewer = ImageViewer()
        viewer.resize(800, 600)
        viewer.show()
        self.app.processEvents()
        # Small image so fit is already >1; zoom further above 1:1.
        image = QImage(200, 120, QImage.Format.Format_RGB32)
        image.fill(QColor("#808080"))
        viewer._handle_image_loaded(Path("small.jpg"), viewer._load_token, image, "")
        self.app.processEvents()
        viewer.zoom_by(2.0)
        self.app.processEvents()
        effective = viewer.transform().m11() * viewer._display_scale
        self.assertGreaterEqual(effective, 1.0)

        self.assertIsNone(viewer._target_hq_size())
        viewer._finish_zoom_interaction()
        self.app.processEvents()
        self.assertEqual(viewer._hq_threads, {})
        self.assertEqual(viewer._pixmap_item.pixmap().width(), 200)

        viewer.close()
        viewer.deleteLater()
        self.app.processEvents()

    def test_viewer_abort_hq_tolerates_deleted_thread_wrappers(self):
        viewer = ImageViewer()
        # Simulate a finished HQ thread whose C++ object was already deleteLater'd
        # while the Python wrapper is still tracked in _hq_threads.
        dead_thread = QThread(viewer)
        dead_thread.deleteLater()
        self.app.processEvents()
        viewer._hq_threads[999] = (dead_thread, None)

        viewer._abort_hq()
        viewer.load_image  # keep attribute access for readability
        # Must not raise; entry should be pruned.
        self.assertNotIn(999, viewer._hq_threads)
        viewer.close()
        viewer.deleteLater()
        self.app.processEvents()

    def test_viewer_does_not_show_filename_loading_text_when_switching_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "next-image.png"
            image = QImage(12, 12, QImage.Format.Format_RGB32)
            image.fill(QColor("#427f78"))
            image.save(str(image_path))
            viewer = ImageViewer()

            viewer.load_image(image_path)
            loaded = self._process_events_until(
                lambda: viewer._loading_path is None and not viewer._active_threads,
                timeout=1.0,
            )
            visible_loading_text = (
                viewer._message_item.toPlainText()
                if viewer._message_item.isVisible()
                else ""
            )
            viewer.shutdown()
            viewer.close()
            viewer.deleteLater()
            self.app.processEvents()

            self.assertTrue(loaded)
            self.assertNotIn(image_path.name, visible_loading_text)

    def test_path_labels_keep_full_path_tooltip_without_tight_width_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)
            long_path = str(
                Path(tmp)
                / "incoming"
                / "client"
                / "project"
                / "round-04"
                / "very-deep-review-folder"
            )

            label = window._path_label("No source folder")
            label.setText(long_path)
            window.close()

            self.assertEqual(label.toolTip(), long_path)
            self.assertGreater(label.maximumWidth(), 300)

    def test_key_bindings_dialog_uses_workbench_dialog_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)

            dialog, row_list = window._build_key_bindings_dialog()
            title = dialog.findChild(QLabel, "DialogTitle")
            key_header = dialog.findChild(QLabel, "KeyColumnHeader")
            folder_header = dialog.findChild(QLabel, "FolderColumnHeader")
            drag_handle = dialog.findChild(QLabel, "DragHandle")
            dialog.close()
            window.close()

            self.assertEqual(dialog.objectName(), "WorkbenchDialog")
            self.assertGreaterEqual(dialog.minimumWidth(), 560)
            self.assertIsNotNone(row_list)
            self.assertEqual(row_list.objectName(), "KeyBindingsList")
            self.assertEqual(
                row_list.verticalScrollBarPolicy(),
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
            )
            self.assertIsNotNone(title)
            self.assertIsNotNone(key_header)
            self.assertIsNotNone(folder_header)
            self.assertIsNotNone(drag_handle)

    def test_key_bindings_dialog_rows_remain_operable_at_default_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT", "q": "QK", "g": "GE", "m": "MA"},
                    "binding_profiles": {
                        "default": {"p": "PT", "q": "QK", "g": "GE", "m": "MA"}
                    },
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)

            dialog, row_list = window._build_key_bindings_dialog()
            first_item = row_list.item(0)
            first_row = row_list.itemWidget(first_item)
            dialog.close()
            window.close()

            self.assertGreaterEqual(dialog.minimumWidth(), 760)
            self.assertGreaterEqual(dialog.minimumHeight(), 520)
            self.assertGreaterEqual(row_list.minimumHeight(), 240)
            self.assertLessEqual(row_list.spacing(), 2)
            self.assertLessEqual(first_item.sizeHint().height(), 38)
            self.assertGreaterEqual(first_row.key_edit.height(), 28)
            self.assertGreaterEqual(first_row.folder_edit.height(), 28)
            self.assertGreaterEqual(first_row.delete_button.height(), 28)

    def test_key_bindings_dialog_expands_for_many_existing_mappings(self):
        bindings = {
            key: f"Folder{index}"
            for index, key in enumerate("abcdefghijkl")
        }

        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": bindings,
                    "binding_profiles": {"default": bindings},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)

            dialog, row_list = window._build_key_bindings_dialog()
            initial_height = dialog.size().height()
            dialog.close()
            window.close()

            self.assertGreater(initial_height, 520)
            self.assertGreater(row_list.minimumHeight(), 260)

    def test_key_bindings_dialog_item_shadow_aligns_with_row_widget(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT", "q": "QK"},
                    "binding_profiles": {"default": {"p": "PT", "q": "QK"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)

            dialog, row_list = window._build_key_bindings_dialog()
            dialog.show()
            self.app.processEvents()
            row_list.doItemsLayout()
            self.app.processEvents()
            item = row_list.item(1)
            row_widget = row_list.itemWidget(item)
            item_rect = row_list.visualItemRect(item)
            row_rect = row_widget.geometry()
            dialog.close()
            window.close()

            self.assertEqual(row_rect.x(), item_rect.x())
            self.assertEqual(row_rect.y(), item_rect.y())
            self.assertEqual(row_rect.width(), item_rect.width())
            self.assertEqual(row_rect.height(), item_rect.height())

    def test_key_bindings_dialog_uses_icon_handle_instead_of_drag_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)

            dialog, _row_list = window._build_key_bindings_dialog()
            drag_handle = dialog.findChild(QLabel, "DragHandle")
            dialog.close()
            window.close()

            self.assertIsNotNone(drag_handle)
            self.assertNotEqual(drag_handle.text(), "Drag")
            self.assertEqual(drag_handle.toolTip(), "Drag to reorder")

    def test_key_bindings_dialog_move_clears_selection_highlight(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT", "q": "QK"},
                    "binding_profiles": {"default": {"p": "PT", "q": "QK"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)

            dialog, row_list = window._build_key_bindings_dialog()
            row_list.setCurrentRow(1)
            window._move_key_binding_row(row_list, 1, 0)
            dialog.close()
            window.close()

            self.assertEqual(row_list.currentRow(), -1)
            self.assertEqual(row_list.selectedItems(), [])

    def test_key_bindings_dialog_can_add_more_mapping_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)

            dialog, row_list = window._build_key_bindings_dialog()
            initial_count = row_list.count()
            add_button = dialog.findChild(QPushButton, "AddMappingButton")
            add_button.click()
            dialog.close()
            window.close()

            self.assertIsNotNone(add_button)
            self.assertEqual(row_list.count(), initial_count + 1)

    def test_key_bindings_dialog_delete_row_removes_without_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT", "q": "QK"},
                    "binding_profiles": {"default": {"p": "PT", "q": "QK"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)

            dialog, row_list = window._build_key_bindings_dialog()
            delete_button = dialog.findChild(QPushButton, "DeleteMappingButton")
            calls = []
            window._confirm_delete_key_mapping = lambda key, folder: calls.append(
                (key, folder)
            ) or False
            delete_button.click()
            remaining_rows = self._dialog_key_row_texts(row_list)
            dialog.close()
            window.close()

            self.assertIsNotNone(delete_button)
            self.assertEqual(calls, [])
            self.assertNotIn(("p", "PT"), remaining_rows)

    def test_key_bindings_dialog_reordered_rows_persist_in_visual_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT", "q": "QK", "g": "GE"},
                    "binding_profiles": {"default": {"p": "PT", "q": "QK", "g": "GE"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)
            dialog, row_list = window._build_key_bindings_dialog()

            window._move_key_binding_row(row_list, 2, 0)
            bindings = window._collect_key_binding_rows(row_list)
            window.update_active_bindings(bindings)
            dialog.close()
            window.close()

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            keys = list(saved["image_classifier"]["binding_profiles"]["default"].keys())
            self.assertEqual(keys[:3], ["g", "p", "q"])
            self.assertEqual(
                list(saved["image_classifier"]["default_key_bindings"].keys())[:3],
                ["g", "p", "q"],
            )

    def test_key_binding_sort_key_orders_letters_digits_then_symbols(self):
        sort_key = AnnotationWorkbench._key_binding_sort_key
        ordered = sorted(
            [",", "2", "B", "a", "1", "b", "A", ""],
            key=sort_key,
        )
        self.assertEqual(ordered, ["a", "A", "b", "B", "1", "2", ",", ""])

    def test_key_bindings_dialog_sort_by_key_reorders_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {
                        ",": "Comma",
                        "B": "UpperB",
                        "2": "Two",
                        "a": "LowerA",
                        "1": "One",
                        "b": "LowerB",
                        "A": "UpperA",
                    },
                    "binding_profiles": {
                        "default": {
                            ",": "Comma",
                            "B": "UpperB",
                            "2": "Two",
                            "a": "LowerA",
                            "1": "One",
                            "b": "LowerB",
                            "A": "UpperA",
                        }
                    },
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)
            dialog, row_list = window._build_key_bindings_dialog()
            items_before = [row_list.item(row) for row in range(row_list.count())]
            widgets_before = [
                row_list.itemWidget(item) for item in items_before
            ]

            sort_button = dialog.findChild(QPushButton, "SortMappingButton")
            self.assertIsNotNone(sort_button)
            sort_button.click()

            filled_keys = [
                key
                for key, folder in self._dialog_key_row_texts(row_list)
                if key or folder
            ]
            bindings = window._collect_key_binding_rows(row_list)
            window.update_active_bindings(bindings)
            dialog.close()
            window.close()

            self.assertEqual(
                [row_list.item(row) for row in range(row_list.count())],
                items_before,
            )
            self.assertEqual(
                [row_list.itemWidget(item) for item in items_before],
                widgets_before,
            )
            self.assertEqual(filled_keys, ["a", "A", "b", "B", "1", "2", ","])
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(
                list(saved["image_classifier"]["binding_profiles"]["default"].keys()),
                ["a", "A", "b", "B", "1", "2", ","],
            )

    def test_key_bindings_dialog_rejects_case_only_target_folder_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "pt", "P": "PT"},
                    "binding_profiles": {"default": {"p": "pt", "P": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)
            dialog, row_list = window._build_key_bindings_dialog()

            with self.assertRaises(ValueError) as context:
                window._collect_key_binding_rows(row_list)

            dialog.close()
            window.close()
            self.assertIn("Target folders differ only by case", str(context.exception))

    def test_key_bindings_dialog_rejects_duplicate_target_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT", "q": "PT"},
                    "binding_profiles": {"default": {"p": "PT", "q": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)
            dialog, row_list = window._build_key_bindings_dialog()

            with self.assertRaises(ValueError) as context:
                window._collect_key_binding_rows(row_list)

            dialog.close()
            window.close()
            self.assertIn("Target folder is duplicated", str(context.exception))

    def test_key_bindings_dialog_invalid_save_stays_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT", "q": "QK"},
                    "binding_profiles": {"default": {"p": "PT", "q": "QK"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)
            dialog, row_list = window._build_key_bindings_dialog()
            second_row = row_list.itemWidget(row_list.item(1))
            second_row.folder_edit.setText("PT")
            actions = dialog.findChild(QDialogButtonBox, "DialogActions")
            save_button = actions.button(QDialogButtonBox.StandardButton.Save)

            dialog.show()
            self.app.processEvents()
            with patch("qt_workbench.QMessageBox.warning") as warning:
                save_button.click()
                self.app.processEvents()

            self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
            self.assertTrue(dialog.isVisible())
            dialog.close()
            window.close()
            warning.assert_called_once()

    def test_key_bindings_dialog_cancelled_reorder_does_not_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT", "q": "QK"},
                    "binding_profiles": {"default": {"p": "PT", "q": "QK"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)
            dialog, row_list = window._build_key_bindings_dialog()

            window._move_key_binding_row(row_list, 1, 0)
            dialog.reject()
            window.close()

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(
                list(saved["image_classifier"]["binding_profiles"]["default"].keys()),
                ["p", "q"],
            )

    def test_key_bindings_dialog_rejected_edits_do_not_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT", "q": "QK"},
                    "binding_profiles": {"default": {"p": "PT", "q": "QK"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)
            dialog, row_list = window._build_key_bindings_dialog()
            second_row = row_list.itemWidget(row_list.item(1))
            second_row.folder_edit.setText("Changed")
            window._build_key_bindings_dialog = lambda: (dialog, row_list)
            dialog.exec = lambda: QDialog.DialogCode.Rejected

            window.configure_bindings()

            dialog.close()
            window.close()
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(
                saved["image_classifier"]["binding_profiles"]["default"],
                {"p": "PT", "q": "QK"},
            )

    def test_profile_delete_button_keeps_confirmation_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"x": "XR"},
                    "binding_profiles": {
                        "default": {"p": "PT"},
                        "review": {"x": "XR"},
                    },
                    "active_binding_profile": "review",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)
            calls = []
            window.delete_binding_profile = lambda confirm=True: calls.append(confirm) or False
            window.delete_profile_button.clicked.disconnect()
            window.delete_profile_button.clicked.connect(window._request_delete_binding_profile)

            window.delete_profile_button.click()
            window.close()

            self.assertEqual(calls, [True])

    def test_recent_panel_is_taller_and_history_text_prioritizes_operation(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)
            record = MoveRecord(
                source=Path("A4AOH12-1_DDR65121240A2_305_long_name.jpg"),
                target=Path("PT/A4AOH12-1_DDR65121240A2_305_long_name.jpg"),
                key="p",
                category="PT",
            )

            move_text = window._format_move_record(record)
            window._record_operation(move_text)
            item_text = window.history_list.item(0).text()
            window.close()

            self.assertGreaterEqual(window.history_list.maximumHeight(), 330)
            self.assertEqual(
                window.history_list.horizontalScrollBarPolicy(),
                Qt.ScrollBarPolicy.ScrollBarAsNeeded,
            )
            self.assertTrue(move_text.startswith("p -> PT:"))
            self.assertTrue(item_text.startswith("p -> PT:"))

    def test_inspector_panel_fits_default_splitter_width_without_horizontal_scrollbar(
        self,
    ):
        """Right panel must not ship with a permanent horizontal scrollbar."""
        from PySide6.QtWidgets import QScrollArea

        bindings = {
            "e": "M2_WE_OP_G",
            "E": "M2_WE_OP_X",
            "o": "T3_XX_PO_G",
            "p": "M2_SP_PI",
            "q": "M1_PH_QK_P",
            "t": "T3_SP_PI_G",
            "T": "T3_SP_PI_P",
            "/": "UN",
            ".": "不要了",
            "2": "M1_PH_F2",
        }
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": bindings,
                    "binding_profiles": {"ADC_A9950": bindings},
                    "active_binding_profile": "ADC_A9950",
                    "classification_columns": 2,
                    "window_size": [1280, 820],
                    "shortcuts": {},
                },
            )
            window = AnnotationWorkbench(ConfigManager(str(config_path)))
            window.show()
            self.app.processEvents()
            window.splitter.setSizes([270, 700, 310])
            self.app.processEvents()

            scroll = window.inspector_panel.findChildren(QScrollArea)[0]
            panel = scroll.widget()
            viewport_width = scroll.viewport().width()
            hbar = scroll.horizontalScrollBar()

            self.assertEqual(
                scroll.horizontalScrollBarPolicy(),
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
            )
            self.assertLessEqual(panel.width(), viewport_width)
            self.assertEqual(hbar.maximum(), 0)
            self.assertEqual(window.xml_pair_button.text(), "LinkXML")
            # Header controls stay inside the visible inspector width.
            self.assertLessEqual(
                window.classification_columns_combo.geometry().right(),
                panel.width() - panel.layout().contentsMargins().right(),
            )
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_recent_move_text_marks_xml_pair_moves(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)
            record = MoveRecord(
                source=Path("a.jpg"),
                target=Path("PT/a.jpg"),
                key="p",
                category="PT",
                xml_source=Path("a.xml"),
                xml_target=Path("PT/a.xml"),
            )

            move_text = window._format_move_record(record)
            window.close()

            self.assertEqual(move_text, "p -> PT + XML: a.jpg")

    def test_recent_move_text_omits_xml_marker_for_image_only_moves(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._write_config(
                tmp,
                {
                    "supported_formats": [".jpg"],
                    "default_key_bindings": {"p": "PT"},
                    "binding_profiles": {"default": {"p": "PT"}},
                    "active_binding_profile": "default",
                    "window_size": [1200, 800],
                    "shortcuts": {},
                },
            )
            window = self._workbench(config_path)
            record = MoveRecord(
                source=Path("a.jpg"),
                target=Path("PT/a.jpg"),
                key="p",
                category="PT",
                xml_target=None,
            )

            move_text = window._format_move_record(record)
            window.close()

            self.assertEqual(move_text, "p -> PT: a.jpg")

    def test_dialog_and_form_controls_have_dark_theme_rules(self):
        required_selectors = [
            "QDialog",
            "QLineEdit",
            "QListWidget",
            "QAbstractSpinBox",
            "QSpinBox",
            "QDialogButtonBox QPushButton",
        ]

        for selector in required_selectors:
            with self.subTest(selector=selector):
                self.assertIn(selector, APP_STYLESHEET)


if __name__ == "__main__":
    unittest.main()
