# XML Pair Move Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an off-by-default XML pair move mode that moves a matching `image_stem.xml` with the classified image and preserves the pair through conflict renaming and undo.

**Architecture:** Keep destructive filesystem behavior in `classifier_core.py`, where scanning, move, conflict naming, and undo already live. The Qt workbench owns only the checkable mode button, passes the mode into each `ClassifierSession`, and formats Recent text based on the resulting `MoveRecord`.

**Tech Stack:** Python, pathlib, shutil, dataclasses, unittest, PySide6/Qt.

---

## Scope Check

The spec covers one cohesive feature across the existing core and Qt workbench:
pair-aware classification moves. It does not need decomposition into separate
sub-project specs because the UI toggle cannot work without the core session
mode, and both are testable in the existing unit test suites.

## File Structure

- Modify `classifier_core.py`: add pair-safe target resolution, session mode
  state, optional XML paths on `MoveRecord`, XML classification move behavior,
  and XML-aware undo.
- Modify `tests/test_classifier_core.py`: add coverage for default behavior,
  XML mode move behavior, conflict naming, missing XML, and undo conflict rules.
- Modify `qt_workbench.py`: add the `XML` mode button, session propagation,
  presentation visibility handling, and Recent text marker.
- Modify `tests/test_qt_workbench.py`: add coverage for the button default,
  toggle propagation, new session seeding, and Recent marker.
- Modify `USER_GUIDE.md`: document the new button and exact missing-XML behavior.

---

### Task 1: Core XML Pair Classification

**Files:**
- Modify: `tests/test_classifier_core.py`
- Modify: `classifier_core.py`

- [ ] **Step 1: Add failing core classification tests**

Insert these tests in `tests/test_classifier_core.py` after
`test_classify_current_treats_lowercase_and_uppercase_keys_separately`:

```python
    def test_classify_current_default_mode_leaves_matching_xml_in_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            (source / "a.xml").write_text("<annotation />", encoding="utf-8")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
            )
            session.refresh()

            record = session.classify_current("p")

            self.assertEqual(record.source, source / "a.jpg")
            self.assertEqual(record.target, target / "PT" / "a.jpg")
            self.assertIsNone(record.xml_source)
            self.assertIsNone(record.xml_target)
            self.assertTrue((source / "a.xml").exists())
            self.assertFalse((target / "PT" / "a.xml").exists())

    def test_classify_current_xml_pair_mode_moves_matching_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            (source / "a.xml").write_text("<annotation />", encoding="utf-8")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
                move_xml_pairs=True,
            )
            session.refresh()

            record = session.classify_current("p")

            self.assertEqual(record.target, target / "PT" / "a.jpg")
            self.assertEqual(record.xml_source, source / "a.xml")
            self.assertEqual(record.xml_target, target / "PT" / "a.xml")
            self.assertFalse((source / "a.jpg").exists())
            self.assertFalse((source / "a.xml").exists())
            self.assertTrue((target / "PT" / "a.jpg").exists())
            self.assertTrue((target / "PT" / "a.xml").exists())

    def test_classify_current_xml_pair_mode_allows_missing_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
                move_xml_pairs=True,
            )
            session.refresh()

            record = session.classify_current("p")

            self.assertEqual(record.target, target / "PT" / "a.jpg")
            self.assertIsNone(record.xml_source)
            self.assertIsNone(record.xml_target)
            self.assertTrue((target / "PT" / "a.jpg").exists())

    def test_classify_current_xml_pair_mode_keeps_pair_stem_on_image_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            category = target / "PT"
            source.mkdir()
            category.mkdir(parents=True)
            (source / "a.jpg").write_bytes(b"a")
            (source / "a.xml").write_text("<annotation />", encoding="utf-8")
            (category / "a.jpg").write_bytes(b"existing")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
                move_xml_pairs=True,
            )
            session.refresh()

            record = session.classify_current("p")

            self.assertEqual(record.target, category / "a_1.jpg")
            self.assertEqual(record.xml_target, category / "a_1.xml")
            self.assertTrue((category / "a_1.jpg").exists())
            self.assertTrue((category / "a_1.xml").exists())

    def test_classify_current_xml_pair_mode_skips_conflicting_xml_pair_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            category = target / "PT"
            source.mkdir()
            category.mkdir(parents=True)
            (source / "a.jpg").write_bytes(b"a")
            (source / "a.xml").write_text("<annotation />", encoding="utf-8")
            (category / "a.jpg").write_bytes(b"existing image")
            (category / "a_1.xml").write_text("existing xml", encoding="utf-8")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
                move_xml_pairs=True,
            )
            session.refresh()

            record = session.classify_current("p")

            self.assertEqual(record.target, category / "a_2.jpg")
            self.assertEqual(record.xml_target, category / "a_2.xml")
            self.assertTrue((category / "a_2.jpg").exists())
            self.assertTrue((category / "a_2.xml").exists())
            self.assertEqual(
                (category / "a_1.xml").read_text(encoding="utf-8"),
                "existing xml",
            )
```

- [ ] **Step 2: Run core tests and verify the new tests fail**

Run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest discover -s tests -p test_classifier_core.py -v
```

Expected: FAIL because `MoveRecord` has no `xml_source` or `xml_target`, and
`ClassifierSession` does not accept `move_xml_pairs`.

- [ ] **Step 3: Add pair target resolution and XML classification moves**

In `classifier_core.py`, add this helper after `resolve_target_path`:

```python
def _numbered_filename(stem: str, suffix: str, counter: int) -> str:
    if counter == 0:
        return f"{stem}{suffix}"
    return f"{stem}_{counter}{suffix}"


def resolve_pair_target_paths(target_dir: Path, image_filename: str) -> tuple[Path, Path]:
    target_dir = Path(target_dir)
    image_path = Path(image_filename)
    counter = 0
    while True:
        target_stem = image_path.stem
        image_target = target_dir / _numbered_filename(
            target_stem,
            image_path.suffix,
            counter,
        )
        xml_target = target_dir / _numbered_filename(target_stem, ".xml", counter)
        if not image_target.exists() and not xml_target.exists():
            return image_target, xml_target
        counter += 1
```

Replace `MoveRecord` with:

```python
@dataclass
class MoveRecord:
    source: Path
    target: Path
    key: str
    category: str
    xml_source: Optional[Path] = None
    xml_target: Optional[Path] = None
```

Add this field at the end of `ClassifierSession`'s dataclass fields:

```python
    move_xml_pairs: bool = False
```

Replace `ClassifierSession.classify_current` with:

```python
    def classify_current(self, key: str) -> MoveRecord:
        if key not in self.key_bindings:
            raise KeyNotBoundError(f"No category is bound to key: {key}")

        source = self.current_image()
        if source is None:
            raise NoCurrentImageError("No image is selected.")
        if not source.exists():
            raise SourceFileMissingError(f"Source image no longer exists: {source}")

        category = self.key_bindings[key]
        category_dir = Path(self.target_folder) / category
        xml_source = source.with_suffix(".xml") if self.move_xml_pairs else None
        xml_target: Optional[Path] = None

        if xml_source is not None and xml_source.is_file():
            target, xml_target = resolve_pair_target_paths(category_dir, source.name)
        else:
            xml_source = None
            target = resolve_target_path(category_dir, source.name)

        record = MoveRecord(
            source=source,
            target=target,
            key=key,
            category=category,
            xml_source=xml_source,
            xml_target=xml_target,
        )

        image_moved = False
        try:
            category_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            image_moved = True
            if xml_source is not None and xml_target is not None:
                shutil.move(str(xml_source), str(xml_target))
        except Exception as exc:
            rollback_error = None
            if image_moved and target.exists() and not source.exists():
                try:
                    shutil.move(str(target), str(source))
                except Exception as rollback_exc:
                    rollback_error = rollback_exc
            message = f"Failed to move {source} to {target}: {exc}"
            if rollback_error is not None:
                message += f"; rollback failed: {rollback_error}"
            raise MoveFailedError(message) from exc

        if source in self.images:
            removed_index = self.images.index(source)
            self.images.pop(removed_index)
            self.current_index = min(removed_index, max(len(self.images) - 1, 0))
        else:
            self.current_index = min(self.current_index, max(len(self.images) - 1, 0))

        self.history.append(record)
        return record
```

- [ ] **Step 4: Run core tests and verify classification behavior passes**

Run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest discover -s tests -p test_classifier_core.py -v
```

Expected: classification XML tests PASS. Undo XML tests do not exist yet.

- [ ] **Step 5: Commit core classification changes**

Run:

```powershell
git add classifier_core.py tests/test_classifier_core.py
git commit -m "feat: move xml pairs during classification"
```

Expected: commit succeeds in a real repository. If the environment reports
`fatal: not a git repository`, record that and continue without pretending the
commit happened.

---

### Task 2: XML-Aware Undo

**Files:**
- Modify: `tests/test_classifier_core.py`
- Modify: `classifier_core.py`

- [ ] **Step 1: Add failing XML undo tests**

Insert these tests in `tests/test_classifier_core.py` after
`test_undo_last_restores_latest_move_at_current_index`:

```python
    def test_undo_last_restores_moved_xml_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            (source / "a.xml").write_text("<annotation />", encoding="utf-8")
            (source / "b.jpg").write_bytes(b"b")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
                move_xml_pairs=True,
            )
            session.refresh()
            moved = session.classify_current("p")

            restored = session.undo_last()

            self.assertEqual(restored, moved)
            self.assertTrue((source / "a.jpg").exists())
            self.assertTrue((source / "a.xml").exists())
            self.assertFalse((target / "PT" / "a.jpg").exists())
            self.assertFalse((target / "PT" / "a.xml").exists())
            self.assertEqual([p.name for p in session.images], ["a.jpg", "b.jpg"])

    def test_undo_last_refuses_to_overwrite_existing_source_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending"
            target = root / "classified"
            source.mkdir()
            (source / "a.jpg").write_bytes(b"a")
            (source / "a.xml").write_text("<annotation />", encoding="utf-8")
            session = ClassifierSession(
                source_folder=source,
                target_folder=target,
                supported_formats=[".jpg"],
                key_bindings={"p": "PT"},
                move_xml_pairs=True,
            )
            session.refresh()
            session.classify_current("p")
            (source / "a.xml").write_text("new xml", encoding="utf-8")

            with self.assertRaises(UndoConflictError):
                session.undo_last()

            self.assertTrue((target / "PT" / "a.jpg").exists())
            self.assertTrue((target / "PT" / "a.xml").exists())
            self.assertEqual(
                (source / "a.xml").read_text(encoding="utf-8"),
                "new xml",
            )
```

- [ ] **Step 2: Run core tests and verify undo XML tests fail**

Run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest discover -s tests -p test_classifier_core.py -v
```

Expected: FAIL because `undo_last` restores only the image and does not check
the original XML path.

- [ ] **Step 3: Replace undo implementation with XML-aware restore**

Replace `ClassifierSession.undo_last` in `classifier_core.py` with:

```python
    def undo_last(self) -> MoveRecord:
        if not self.history:
            raise NoCurrentImageError("No move operation can be undone.")

        record = self.history[-1]
        if record.source.exists():
            raise UndoConflictError(f"Undo would overwrite existing file: {record.source}")
        if record.xml_source is not None and record.xml_source.exists():
            raise UndoConflictError(
                f"Undo would overwrite existing XML file: {record.xml_source}"
            )
        if not record.target.exists():
            raise SourceFileMissingError(f"Moved file no longer exists: {record.target}")
        if record.xml_target is not None and not record.xml_target.exists():
            raise SourceFileMissingError(
                f"Moved XML file no longer exists: {record.xml_target}"
            )

        image_restored = False
        try:
            record.source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(record.target), str(record.source))
            image_restored = True
            if record.xml_source is not None and record.xml_target is not None:
                record.xml_source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(record.xml_target), str(record.xml_source))
        except Exception as exc:
            rollback_error = None
            if image_restored and record.source.exists() and not record.target.exists():
                try:
                    shutil.move(str(record.source), str(record.target))
                except Exception as rollback_exc:
                    rollback_error = rollback_exc
            message = f"Failed to undo move {record.target}: {exc}"
            if rollback_error is not None:
                message += f"; rollback failed: {rollback_error}"
            raise MoveFailedError(message) from exc

        insert_at = min(self.current_index, len(self.images))
        self.images.insert(insert_at, record.source)
        self.current_index = insert_at
        self.history.pop()
        return record
```

- [ ] **Step 4: Run core tests and verify all core behavior passes**

Run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest discover -s tests -p test_classifier_core.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit XML undo changes**

Run:

```powershell
git add classifier_core.py tests/test_classifier_core.py
git commit -m "feat: restore xml pairs on undo"
```

Expected: commit succeeds in a real repository. If git is unavailable, record the
failure and continue.

---

### Task 3: Qt XML Mode Toggle

**Files:**
- Modify: `tests/test_qt_workbench.py`
- Modify: `qt_workbench.py`

- [ ] **Step 1: Add failing Qt mode button tests**

Insert these tests in `tests/test_qt_workbench.py` after
`test_classification_buttons_restore_persisted_two_column_mode`:

```python
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

            self.assertEqual(window.xml_pair_button.text(), "XML")
            self.assertFalse(window.xml_pair_button.isChecked())
            self.assertFalse(window.move_xml_pairs)

    def test_xml_pair_mode_toggle_updates_current_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            window, _source = self._loaded_workbench(tmp, names=("a.jpg",))

            self.assertFalse(window.session.move_xml_pairs)
            window.xml_pair_button.click()
            window.close()

            self.assertTrue(window.move_xml_pairs)
            self.assertTrue(window.session.move_xml_pairs)

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
```

- [ ] **Step 2: Run Qt workbench tests and verify the new tests fail**

Run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest discover -s tests -p test_qt_workbench.py -v
```

Expected: FAIL because `AnnotationWorkbench` has no `xml_pair_button` or
`move_xml_pairs`.

- [ ] **Step 3: Add XML button state and session propagation**

In `qt_workbench.py`, add this assignment in `AnnotationWorkbench.__init__`
after `_previous_image_paths` is initialized and before `_build_ui()` runs:

```python
        self.move_xml_pairs = False
```

In `_build_inspector_panel`, create the XML button after
`self.classification_columns_button` is configured:

```python
        self.xml_pair_button = QPushButton("XML", panel)
        self.xml_pair_button.setObjectName("SubtleButton")
        self.xml_pair_button.setCheckable(True)
        self.xml_pair_button.setChecked(self.move_xml_pairs)
        self.xml_pair_button.setToolTip("Move matching .xml with image")
        self.xml_pair_button.clicked.connect(self._toggle_xml_pair_mode)
```

In the same header layout, add the XML button before the column-density button:

```python
        classification_header.addWidget(title)
        classification_header.addStretch(1)
        classification_header.addWidget(self.xml_pair_button)
        classification_header.addWidget(self.classification_columns_button)
```

Add this method near `_toggle_classification_columns`:

```python
    def _toggle_xml_pair_mode(self, checked: bool = False) -> None:
        self.move_xml_pairs = bool(checked)
        if self.session is not None:
            self.session.move_xml_pairs = self.move_xml_pairs
        status = (
            "XML pair move enabled"
            if self.move_xml_pairs
            else "XML pair move disabled"
        )
        self._set_status(status)
```

In `_toggle_presentation_mode`, hide the XML button together with the other
workbench controls:

```python
        self.xml_pair_button.setVisible(not enabled)
```

In `_create_session`, pass the current mode into `ClassifierSession`:

```python
        self.session = ClassifierSession(
            source_folder=self.source_folder,
            target_folder=self.target_folder,
            supported_formats=list(
                self.classifier_config.get("supported_formats", [".jpg", ".png"])
            ),
            key_bindings=dict(self.profiles.get(self.active_profile, {})),
            move_xml_pairs=self.move_xml_pairs,
        )
```

- [ ] **Step 4: Run Qt workbench tests and verify XML button tests pass**

Run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest discover -s tests -p test_qt_workbench.py -v
```

Expected: PASS for the XML button tests and no regression in existing Qt tests.

- [ ] **Step 5: Commit Qt toggle changes**

Run:

```powershell
git add qt_workbench.py tests/test_qt_workbench.py
git commit -m "feat: add xml pair mode toggle"
```

Expected: commit succeeds in a real repository. If git is unavailable, record the
failure and continue.

---

### Task 4: Recent Text XML Marker

**Files:**
- Modify: `tests/test_qt_workbench.py`
- Modify: `qt_workbench.py`

- [ ] **Step 1: Add failing Recent marker test**

Insert this test in `tests/test_qt_workbench.py` after
`test_recent_panel_is_taller_and_history_text_prioritizes_operation`:

```python
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
```

- [ ] **Step 2: Run Qt workbench tests and verify the Recent marker test fails**

Run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest discover -s tests -p test_qt_workbench.py -v
```

Expected: FAIL because `_format_move_record` still returns `p -> PT: a.jpg`.

- [ ] **Step 3: Add XML marker formatting**

Replace `_format_move_record` in `qt_workbench.py` with:

```python
    def _format_move_record(self, record: MoveRecord) -> str:
        xml_marker = " + XML" if record.xml_target is not None else ""
        return f"{record.key} -> {record.category}{xml_marker}: {record.source.name}"
```

- [ ] **Step 4: Run Qt workbench tests and verify Recent formatting passes**

Run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest discover -s tests -p test_qt_workbench.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit Recent marker changes**

Run:

```powershell
git add qt_workbench.py tests/test_qt_workbench.py
git commit -m "feat: mark xml pair moves in recent history"
```

Expected: commit succeeds in a real repository. If git is unavailable, record the
failure and continue.

---

### Task 5: User Guide Update

**Files:**
- Modify: `USER_GUIDE.md`

- [ ] **Step 1: Document XML pair mode**

In `USER_GUIDE.md`, add this paragraph under section `10. 分类与撤销`, after the
description that classification moves files into `Target\分类文件夹名\图片文件名`:

```markdown
右侧 `Classify` 标题旁的 `XML` 按钮用于切换“图片与同名 XML 标签一起移动”模式。该模式默认关闭；关闭时只移动图片，行为与旧版本一致。开启后，分类 `xx.jpg`、`xx.png` 等图片时，如果 Source 同级存在 `xx.xml`，程序会把图片和 XML 一起移动到同一个分类文件夹。若目标图片因为重名被改为 `xx_1.jpg`，XML 也会同步改为 `xx_1.xml`。如果 Source 中没有对应 XML，程序不会报错，会正常只移动图片。
```

In the undo rule list in the same section, add this bullet:

```markdown
- 如果本次分类同时移动了 XML，撤销会同时恢复图片和 XML；如果原位置已经出现同名图片或 XML，撤销会失败以避免覆盖文件。
```

- [ ] **Step 2: Commit guide update**

Run:

```powershell
git add USER_GUIDE.md
git commit -m "docs: document xml pair move mode"
```

Expected: commit succeeds in a real repository. If git is unavailable, record the
failure and continue.

---

### Task 6: Final Verification

**Files:**
- Verify: `classifier_core.py`
- Verify: `qt_workbench.py`
- Verify: `tests/test_classifier_core.py`
- Verify: `tests/test_qt_workbench.py`
- Verify: `USER_GUIDE.md`

- [ ] **Step 1: Run the full test suite**

Run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest discover -s tests -v
```

Expected: PASS for all tests.

- [ ] **Step 2: Run Python compile check**

Run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m py_compile qt_main.py qt_workbench.py qt_image_viewer.py qt_theme.py classifier_core.py config_manager.py binding_profiles.py
```

Expected: no output and exit code `0`.

- [ ] **Step 3: Inspect changed files**

Run:

```powershell
git status --short
git diff -- classifier_core.py qt_workbench.py tests/test_classifier_core.py tests/test_qt_workbench.py USER_GUIDE.md
```

Expected: only XML pair mode changes appear. If git is unavailable, use the
tests and file review output as the verification record.

- [ ] **Step 4: Final integration commit**

If earlier task commits were skipped, create one final commit:

```powershell
git add classifier_core.py qt_workbench.py tests/test_classifier_core.py tests/test_qt_workbench.py USER_GUIDE.md
git commit -m "feat: add xml pair move mode"
```

Expected: commit succeeds in a real repository. If git is unavailable, report
that implementation is verified but uncommitted.
