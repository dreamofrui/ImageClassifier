# Queue Search And Key Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add exact queue filename search with a single-step `Back` button, and add draggable ordering for key mapping rows in the `Keys` dialog.

**Architecture:** Keep the work in `qt_workbench.py`, because both features are UI/state concerns owned by the Qt workbench. Queue search reuses `ClassifierSession.current_index` and the existing `_sync_after_session_change()` flow. Key mapping order uses a reorderable row list in the dialog and persists through the existing `update_active_bindings()` config path.

**Tech Stack:** Python, PySide6, `unittest`, existing ARS Qt test harness with `QT_QPA_PLATFORM=offscreen`.

---

## File Structure

- Modify `qt_workbench.py`
  - Add queue search controls in `_build_queue_panel()`.
  - Add one-step previous-image state and navigation helpers.
  - Route existing navigation entry points through the helper.
  - Replace the `Keys` dialog grid rows with a reorderable row list.
  - Add small private helpers for collecting and moving key rows.
- Modify `tests/test_qt_workbench.py`
  - Add queue search and `Back` tests.
  - Add key row ordering tests.
  - Keep existing tests passing by updating assertions that inspect the `Keys` dialog internals.
- No expected changes to `classifier_core.py`, `binding_profiles.py`, `config_manager.py`, `ImageClassifier.spec`, or `build.bat`.

## Verification Commands

Use the repository-approved Python interpreter:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest discover -s tests -v
```

For faster focused runs while developing:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest tests.test_qt_workbench -v
```

---

### Task 1: Add Queue Search Tests

**Files:**
- Modify: `tests/test_qt_workbench.py`
- Implementation target after the failing tests: `qt_workbench.py`

- [ ] **Step 1: Add a loaded workbench helper to the test class**

Add this helper inside `QtWorkbenchTest`, near the existing `_workbench()` helper:

```python
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
```

- [ ] **Step 2: Add a test for exact case-insensitive filename search**

Add this test method to `QtWorkbenchTest`:

```python
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
```

- [ ] **Step 3: Add a test for missing filename search**

Add this test method to `QtWorkbenchTest`:

```python
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
```

- [ ] **Step 4: Run the focused test file and verify these tests fail**

Run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest tests.test_qt_workbench -v
```

Expected: FAIL because `AnnotationWorkbench` does not yet define `queue_search_input` or `search_queue_filename()`.

---

### Task 2: Implement Queue Search UI And Exact Matching

**Files:**
- Modify: `qt_workbench.py`
- Test: `tests/test_qt_workbench.py`

- [ ] **Step 1: Add previous-image state in `AnnotationWorkbench.__init__`**

In `AnnotationWorkbench.__init__`, after `_current_loaded_image`, add:

```python
        self._previous_image_path: Path | None = None
```

- [ ] **Step 2: Add search controls in `_build_queue_panel()`**

In `_build_queue_panel()`, after the header is added and before `self.queue_list` is created, create a compact search row:

```python
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.queue_search_input = QLineEdit(panel)
        self.queue_search_input.setObjectName("QueueSearchInput")
        self.queue_search_input.setPlaceholderText("Filename")
        self.queue_search_input.returnPressed.connect(self.search_queue_filename)

        self.queue_back_button = QPushButton("Back", panel)
        self.queue_back_button.setObjectName("SubtleButton")
        self.queue_back_button.clicked.connect(self.back_to_previous_image)

        search_row.addWidget(self.queue_search_input, 1)
        search_row.addWidget(self.queue_back_button)
```

Then add it to the panel layout between the header and the list:

```python
        layout.addLayout(header)
        layout.addLayout(search_row)
        layout.addWidget(self.queue_list, 1)
```

Replace the existing bottom of `_build_queue_panel()`:

```python
        layout.addLayout(header)
        layout.addWidget(self.queue_list, 1)
        return panel
```

with:

```python
        layout.addLayout(header)
        layout.addLayout(search_row)
        layout.addWidget(self.queue_list, 1)
        return panel
```

- [ ] **Step 3: Add the shared navigation helper**

Add these methods near `jump_to_image()`:

```python
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
            self._previous_image_path = current

        self.session.current_index = requested_index
        self._sync_after_session_change(message)
        return True

    def search_queue_filename(self) -> None:
        if not self.session or not self.session.images:
            self._set_status("No image loaded")
            return

        requested_name = self.queue_search_input.text().strip()
        if not requested_name:
            self._set_status("Enter a filename")
            return

        requested_key = requested_name.casefold()
        for index, path in enumerate(self.session.images):
            if path.name.casefold() == requested_key:
                self._set_current_image_index(index, f"Selected {path.name}")
                return

        self._set_status(f"File not found: {requested_name}")
```

- [ ] **Step 4: Update `jump_to_image()` to use the helper**

Replace the body after the initial no-session guard with:

```python
        requested_index = self.jump_spinbox.value() - 1
        self._set_current_image_index(
            requested_index,
            f"Selected image {requested_index + 1}",
        )
```

Keep the existing guard:

```python
        if not self.session or not self.session.images:
            self._set_status("No image loaded")
            return
```

- [ ] **Step 5: Run focused tests and verify Task 1 passes**

Run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest tests.test_qt_workbench -v
```

Expected: the two queue search tests pass.

---

### Task 3: Add Back History Tests

**Files:**
- Modify: `tests/test_qt_workbench.py`
- Implementation target after the failing tests: `qt_workbench.py`

- [ ] **Step 1: Add a test for Back after search**

Add:

```python
    def test_back_returns_to_previous_image_after_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            window, source = self._loaded_workbench(tmp)

            window.queue_search_input.setText("c.png")
            window.search_queue_filename()
            window.back_to_previous_image()
            window.close()

            self.assertEqual(window.session.current_index, 0)
            self.assertEqual(window.image_viewer.loaded[-1], source / "a.jpg")
```

- [ ] **Step 2: Add a test for Back after list click**

Add:

```python
    def test_back_returns_to_previous_image_after_queue_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            window, source = self._loaded_workbench(tmp)

            item = window.queue_list.item(2)
            window._handle_queue_item_clicked(item)
            window.back_to_previous_image()
            window.close()

            self.assertEqual(window.session.current_index, 0)
            self.assertEqual(window.image_viewer.loaded[-1], source / "a.jpg")
```

- [ ] **Step 3: Add a test for Back after index jump**

Add:

```python
    def test_back_returns_to_previous_image_after_jump(self):
        with tempfile.TemporaryDirectory() as tmp:
            window, source = self._loaded_workbench(tmp)

            window.jump_spinbox.setValue(3)
            window.jump_to_image()
            window.back_to_previous_image()
            window.close()

            self.assertEqual(window.session.current_index, 0)
            self.assertEqual(window.image_viewer.loaded[-1], source / "a.jpg")
```

- [ ] **Step 4: Add a test for Back after next, previous, and skip**

Add:

```python
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

            window.back_to_previous_image()
            window.skip_image()
            window.back_to_previous_image()
            window.close()

            self.assertEqual(window.session.current_index, 2)
            self.assertEqual(window.image_viewer.loaded[-1], source / "c.png")
```

- [ ] **Step 5: Add a test for stale Back target**

Add:

```python
    def test_back_reports_unavailable_when_previous_image_left_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            window, _source = self._loaded_workbench(tmp)

            window.next_image()
            stale_path = window._previous_image_path
            window.session.images = [
                path for path in window.session.images if path != stale_path
            ]
            window.back_to_previous_image()
            message = window.statusBar().currentMessage()
            window.close()

            self.assertEqual(window.session.current_index, 1)
            self.assertIsNone(window._previous_image_path)
            self.assertIn("no longer available", message.casefold())
```

- [ ] **Step 6: Run focused tests and verify the new Back tests fail**

Run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest tests.test_qt_workbench -v
```

Expected: FAIL because `back_to_previous_image()` is not implemented and existing navigation entry points do not all record previous image state.

---

### Task 4: Implement Back History Across Navigation Entry Points

**Files:**
- Modify: `qt_workbench.py`
- Test: `tests/test_qt_workbench.py`

- [ ] **Step 1: Implement `back_to_previous_image()`**

Add near `search_queue_filename()`:

```python
    def back_to_previous_image(self) -> None:
        if not self.session or not self.session.images:
            self._set_status("No image loaded")
            return

        if self._previous_image_path is None:
            self._set_status("No previous image")
            return

        try:
            requested_index = self.session.images.index(self._previous_image_path)
        except ValueError:
            self._previous_image_path = None
            self._set_status("Previous image is no longer available")
            return

        current = self.session.current_image()
        previous = self._previous_image_path
        self._set_current_image_index(
            requested_index,
            f"Returned to {previous.name}",
            remember_previous=False,
        )
        self._previous_image_path = current
```

- [ ] **Step 2: Route next/previous through `_set_current_image_index()`**

Replace `next_image()` with:

```python
    def next_image(self) -> None:
        if not self.session or not self.session.images:
            self._set_status("No image loaded")
            return
        requested_index = min(
            self.session.current_index + 1, len(self.session.images) - 1
        )
        self._set_current_image_index(requested_index, "Next image")
```

Replace `previous_image()` with:

```python
    def previous_image(self) -> None:
        if not self.session or not self.session.images:
            self._set_status("No image loaded")
            return
        requested_index = max(self.session.current_index - 1, 0)
        self._set_current_image_index(requested_index, "Previous image")
```

Keep `skip_image()` delegating to `next_image()`:

```python
    def skip_image(self) -> None:
        self.next_image()
```

- [ ] **Step 3: Route queue item clicks through `_set_current_image_index()`**

Replace the final lines of `_handle_queue_item_clicked()` with:

```python
        self._set_current_image_index(row, f"Selected {item.text()}")
```

Keep the existing guards for missing session and invalid row.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest tests.test_qt_workbench -v
```

Expected: queue search and Back tests pass. Existing navigation tests still pass.

---

### Task 5: Add Key Row Ordering Tests

**Files:**
- Modify: `tests/test_qt_workbench.py`
- Implementation target after the failing tests: `qt_workbench.py`

- [ ] **Step 1: Add a helper to read key row order from the dialog**

Add inside `QtWorkbenchTest`:

```python
    def _dialog_key_row_texts(self, row_list):
        rows = []
        for row in range(row_list.count()):
            item = row_list.item(row)
            widget = row_list.itemWidget(item)
            rows.append((widget.key_edit.text(), widget.folder_edit.text()))
        return rows
```

- [ ] **Step 2: Update the existing add-row test to use the row list**

Replace the body of `test_key_bindings_dialog_can_add_more_mapping_rows` after window creation with:

```python
            dialog, row_list = window._build_key_bindings_dialog()
            initial_count = row_list.count()
            add_button = dialog.findChild(QPushButton, "AddMappingButton")
            add_button.click()
            dialog.close()
            window.close()

            self.assertIsNotNone(add_button)
            self.assertEqual(row_list.count(), initial_count + 1)
```

- [ ] **Step 3: Update the existing delete-row test to use the row list**

Replace the body of `test_key_bindings_dialog_delete_row_removes_without_confirmation` after window creation with:

```python
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
```

- [ ] **Step 4: Add a test that row order is persisted after save**

Add:

```python
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
```

- [ ] **Step 5: Add a test that cancelling row reorder does not persist**

Add:

```python
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
```

- [ ] **Step 6: Run focused tests and verify the key-row tests fail**

Run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest tests.test_qt_workbench -v
```

Expected: FAIL because `_build_key_bindings_dialog()` still returns a static list of line edits, and `_move_key_binding_row()` / `_collect_key_binding_rows()` do not exist.

---

### Task 6: Implement Reorderable Key Mapping Rows

**Files:**
- Modify: `qt_workbench.py`
- Test: `tests/test_qt_workbench.py`

- [ ] **Step 1: Import `QAbstractItemView`**

Update the `PySide6.QtWidgets` import block:

```python
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QComboBox,
```

- [ ] **Step 2: Add a row widget class**

Add this class above `AnnotationWorkbench`:

```python
class KeyBindingRow(QFrame):
    def __init__(self, key: str = "", folder: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("KeyBindingRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.drag_handle = QLabel("Drag", self)
        self.drag_handle.setObjectName("DragHandle")
        self.drag_handle.setFixedWidth(44)
        self.drag_handle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.key_edit = QLineEdit(self)
        self.key_edit.setObjectName("KeyInput")
        self.key_edit.setMaxLength(1)
        self.key_edit.setFixedWidth(76)
        self.key_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.key_edit.setText(key)

        self.folder_edit = QLineEdit(self)
        self.folder_edit.setObjectName("FolderInput")
        self.folder_edit.setText(folder)

        self.delete_button = QPushButton("Delete", self)
        self.delete_button.setObjectName("DeleteMappingButton")
        self.delete_button.setFixedWidth(72)

        layout.addWidget(self.drag_handle)
        layout.addWidget(self.key_edit)
        layout.addWidget(self.folder_edit, 1)
        layout.addWidget(self.delete_button)
```

- [ ] **Step 3: Rewrite `_build_key_bindings_dialog()` to return a row list**

Change the signature to:

```python
    def _build_key_bindings_dialog(self) -> tuple[QDialog, QListWidget]:
```

Replace the old `form_panel` grid setup and nested row functions with:

```python
        form_panel = QFrame(dialog)
        form_panel.setObjectName("DialogFormPanel")
        form_layout = QVBoxLayout(form_panel)
        form_layout.setContentsMargins(14, 14, 14, 14)
        form_layout.setSpacing(8)

        header_row = QFrame(form_panel)
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        drag_header = QLabel("", header_row)
        drag_header.setFixedWidth(44)
        key_header = QLabel("Key", header_row)
        key_header.setObjectName("KeyColumnHeader")
        key_header.setFixedWidth(76)
        folder_header = QLabel("Target Folder", header_row)
        folder_header.setObjectName("FolderColumnHeader")
        delete_header = QLabel("", header_row)
        delete_header.setFixedWidth(72)
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
        row_list.setSpacing(6)

        form_layout.addWidget(header_row)
        form_layout.addWidget(row_list)

        def add_mapping_row(key: str = "", folder: str = "") -> None:
            row_widget = KeyBindingRow(key, folder, row_list)
            item = QListWidgetItem(row_list)
            item.setSizeHint(row_widget.sizeHint())
            row_list.addItem(item)
            row_list.setItemWidget(item, row_widget)
            row_widget.delete_button.clicked.connect(
                lambda checked=False, row_item=item: self._delete_key_binding_row(
                    row_list,
                    row_item,
                )
            )
```

Keep the existing `current_bindings`, `empty_rows`, `Add Mapping`, buttons, and final layout code, but update the final return:

```python
        return dialog, row_list
```

- [ ] **Step 4: Add private row helpers**

Add these methods near `_build_key_bindings_dialog()`:

```python
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
        return True

    def _collect_key_binding_rows(self, row_list: QListWidget) -> dict[str, str]:
        bindings: dict[str, str] = {}
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
            bindings[key] = folder
        return bindings
```

- [ ] **Step 5: Update `configure_bindings()` to collect rows in visual order**

Replace the current body after `dialog, key_edits = ...` with:

```python
        dialog, row_list = self._build_key_bindings_dialog()

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            bindings = self._collect_key_binding_rows(row_list)
        except ValueError:
            QMessageBox.warning(
                self,
                "Invalid binding",
                "Each binding needs one key and one target folder.",
            )
            return
        except KeyError as exc:
            QMessageBox.warning(self, "Duplicate key", f"Key '{exc.args[0]}' is duplicated.")
            return

        self.update_active_bindings(bindings)
        self._set_status(f"Saved {len(bindings)} key bindings")
```

- [ ] **Step 6: Run focused tests**

Run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest tests.test_qt_workbench -v
```

Expected: key row ordering tests pass, and existing key dialog tests pass after their expected return value changes.

---

### Task 7: Update UI Structure Tests And Theme Coverage

**Files:**
- Modify: `tests/test_qt_workbench.py`
- Modify: `qt_workbench.py` only if tests expose missing object names

- [ ] **Step 1: Update the dialog shell test for the row list**

In `test_key_bindings_dialog_uses_workbench_dialog_shell`, replace:

```python
            dialog, _key_edits = window._build_key_bindings_dialog()
```

with:

```python
            dialog, row_list = window._build_key_bindings_dialog()
```

Add these assertions before closing:

```python
            drag_handle = dialog.findChild(QLabel, "DragHandle")
            self.assertIsNotNone(row_list)
            self.assertEqual(row_list.objectName(), "KeyBindingsList")
            self.assertIsNotNone(drag_handle)
```

- [ ] **Step 2: Add queue control object assertions to the workflow grouping test**

In `test_controls_are_grouped_by_workflow_area`, add:

```python
            self.assertEqual(window.queue_search_input.parent(), window.queue_panel)
            self.assertEqual(window.queue_back_button.parent(), window.queue_panel)
            self.assertEqual(window.queue_search_input.placeholderText(), "Filename")
            self.assertEqual(window.queue_back_button.text(), "Back")
```

- [ ] **Step 3: Extend theme selector coverage for the row list**

Add `QListWidget` to `required_selectors`:

```python
            "QListWidget",
```

If `APP_STYLESHEET` does not already contain `QListWidget`, add this minimal
rule to `qt_theme.py` inside the stylesheet string:

```css
QListWidget {
    background: #171b21;
    color: #e6e9ee;
    border: 1px solid #2c333d;
    border-radius: 6px;
}
```

- [ ] **Step 4: Run focused tests**

Run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest tests.test_qt_workbench -v
```

Expected: all `tests.test_qt_workbench` tests pass.

---

### Task 8: Full Verification

**Files:**
- No code edits expected unless verification exposes a regression.

- [ ] **Step 1: Run all tests**

Run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Run py_compile for touched runtime modules**

Run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m py_compile qt_workbench.py qt_image_viewer.py qt_theme.py classifier_core.py binding_profiles.py config_manager.py
```

Expected: command exits with code 0 and prints no syntax errors.

- [ ] **Step 3: Inspect the final diff**

Run:

```powershell
git diff -- qt_workbench.py tests/test_qt_workbench.py qt_theme.py docs/superpowers/specs/2026-06-05-queue-search-key-order-design.md docs/superpowers/plans/2026-06-05-queue-search-key-order.md
```

Expected: if this directory is not a Git repository, the command reports that Git cannot find a repository. In that case, inspect the changed files manually and report that Git diff was unavailable.

- [ ] **Step 4: Final status report**

Report:

- implemented queue `Search` and `Back`
- implemented draggable key mapping order saved on `Save`
- tests run and pass, or exact failures if verification did not pass
- no commit was made because the user requested no commit
