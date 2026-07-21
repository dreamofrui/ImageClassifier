# ARS PySide6 Annotation Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current Tkinter image classifier UI with a polished PySide6 / Qt annotation workbench while preserving the existing local file classification behavior.

**Architecture:** Extract file scanning, classification moves, undo history, and path conflict handling into pure Python modules that can be tested without a GUI. Build a new PySide6 workbench around those modules: file queue on the left, high-performance image viewer in the center, controls/status on the right, and presentation mode as a workbench state. Keep the existing Tkinter code available until the Qt workbench reaches feature parity, then switch the packaged entry point.

**Tech Stack:** Python 3.14, PySide6 / Qt, Pillow for supported format compatibility where needed, `unittest`, PyInstaller.

---

## File Structure

Create:

- `classifier_core.py`: testable image scanning, session state, move/undo operations, conflict-safe target path generation.
- `qt_main.py`: temporary Qt entry point during migration.
- `qt_workbench.py`: PySide6 main window, panels, workflow orchestration.
- `qt_image_viewer.py`: zoomable/pannable image viewer built on Qt graphics/view APIs.
- `qt_theme.py`: restrained product UI palette, spacing, and Qt stylesheet helpers.
- `tests/test_classifier_core.py`: unit tests for non-UI annotation behavior.

Modify:

- `requirements.txt`: add PySide6.
- `config.json`: retain existing config fields and profiles.
- `config_manager.py`: keep portable exe-folder config behavior; only adjust if
  `ConfigManager()` no longer resolves the release-folder `config.json`.
- `main.py`: switch from Tkinter launcher to Qt launcher after parity.
- `ImageClassifier.spec` and `build.bat`: include PySide6 packaging changes after Qt entry point is active.
- `docs/specs/ui-redesign.md`: update if implementation decisions resolve open questions.

Do not delete the current `image_classifier.py` until the Qt workbench passes the functional smoke test.

## Behavior Contract To Preserve

- Scan source folders non-recursively.
- Match supported formats case-insensitively by extension.
- Keep stable sorted path order.
- Default target folder to `source_folder.parent`.
- Create category folders lazily during classification.
- Resolve target file conflicts with `_1`, `_2`, and so on before the extension.
- Move files rather than copy them.
- Remove classified images from the queue and clamp the current index at the end.
- Keep undo session-only and last-in-first-out; restore the file at the current queue index.
- Refresh should keep the current file selected if it still exists, otherwise preserve/clamp the current index.
- Preserve `binding_profiles`, `active_binding_profile`, and synchronized `default_key_bindings`.

Settings persistence decision for this plan:

- Keep the current portable `config.json` beside the exe/release folder.
- Do not migrate settings to AppData in this UI rewrite.
- Document that users must preserve their edited `config.json` during upgrades.

## Parallel Work Guidance

This work can use subagents safely if write scopes are kept separate:

- Core worker: `classifier_core.py` and `tests/test_classifier_core.py`.
- Viewer worker: `qt_image_viewer.py`.
- Workbench UI worker: `qt_workbench.py` and `qt_theme.py`.
- Packaging worker: `requirements.txt`, `ImageClassifier.spec`, `build.bat`.
- Review worker: spec/plan review only, no edits.

The lead agent integrates, runs verification, and resolves behavior mismatches.

## Task 1: Add Testable Core Annotation Model

**Files:**

- Create: `tests/test_classifier_core.py`
- Create: `classifier_core.py`

- [x] **Step 1: Write failing tests for scanning and sorting**

```python
import tempfile
import unittest
from pathlib import Path

from classifier_core import scan_images


class ClassifierCoreTest(unittest.TestCase):
    def test_scan_images_returns_supported_files_sorted_non_recursive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b.JPG").write_bytes(b"x")
            (root / "a.png").write_bytes(b"x")
            (root / "notes.txt").write_text("skip")
            nested = root / "nested"
            nested.mkdir()
            (nested / "c.jpg").write_bytes(b"x")

            images = scan_images(root, [".jpg", ".png"])

            self.assertEqual([p.name for p in images], ["a.png", "b.JPG"])
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m unittest tests.test_classifier_core -v
```

Expected: FAIL because `classifier_core` or `scan_images` does not exist.

- [x] **Step 3: Implement `scan_images` minimally**

```python
from pathlib import Path
from typing import Iterable, List


def scan_images(source_folder: Path, supported_formats: Iterable[str]) -> List[Path]:
    normalized = {ext.lower() for ext in supported_formats}
    return sorted(
        path
        for path in Path(source_folder).iterdir()
        if path.is_file() and path.suffix.lower() in normalized
    )
```

- [x] **Step 4: Run test to verify it passes**

Run:

```powershell
python -m unittest tests.test_classifier_core -v
```

Expected: PASS.

- [x] **Step 5: Add failing tests for classification move, name conflict, and undo**

Add tests covering:

- `resolve_target_path(target_dir, "a.jpg")` returns `a_1.jpg` when `a.jpg` exists.
- `ClassifierSession.classify_current("p")` moves the current image into `target/PT/`.
- `ClassifierSession.undo_last()` moves the file back and restores it to the queue.
- Unknown key does not move files and returns or raises a clear error.
- Refresh keeps the current file selected if it still exists.
- Undo refuses to overwrite an existing source path.

- [x] **Step 6: Implement minimal core session**

Expected public API:

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class MoveRecord:
    source: Path
    target: Path
    key: str
    category: str


@dataclass
class ClassifierSession:
    source_folder: Path
    target_folder: Path
    supported_formats: List[str]
    key_bindings: Dict[str, str]
    images: List[Path] = field(default_factory=list)
    current_index: int = 0
    history: List[MoveRecord] = field(default_factory=list)

    def refresh(self) -> None: ...
    def current_image(self) -> Optional[Path]: ...
    def classify_current(self, key: str) -> MoveRecord: ...
    def undo_last(self) -> MoveRecord: ...
```

Move semantics:

- Before moving, verify the current source path still exists.
- Before undo, verify the restore path does not already exist.
- Raise clear domain exceptions such as `KeyNotBoundError`,
  `SourceFileMissingError`, `MoveFailedError`, and `UndoConflictError`.

- [x] **Step 7: Verify full core test set**

Run:

```powershell
python -m unittest tests.test_classifier_core tests.test_binding_profiles -v
```

Expected: all tests pass.

## Task 2: Add PySide6 Dependency And Qt Bootstrap

**Files:**

- Modify: `requirements.txt`
- Create: `qt_main.py`

- [x] **Step 1: Add dependency**

Add:

```text
PySide6>=6.7.0
```

- [x] **Step 2: Create minimal Qt entry point**

`qt_main.py`:

```python
import sys
from PySide6.QtWidgets import QApplication

from config_manager import ConfigManager
from qt_workbench import AnnotationWorkbench


def main():
    app = QApplication(sys.argv)
    config_manager = ConfigManager()
    window = AnnotationWorkbench(config_manager)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 3: Create temporary placeholder workbench**

`qt_workbench.py`:

```python
from PySide6.QtWidgets import QLabel, QMainWindow


class AnnotationWorkbench(QMainWindow):
    def __init__(self, config_manager):
        super().__init__()
        self.config_manager = config_manager
        self.setWindowTitle("ARS Image Annotation Workbench")
        self.resize(1280, 820)
        self.setCentralWidget(QLabel("ARS Workbench"))
```

- [x] **Step 4: Verify import/compile**

Run:

```powershell
python -m py_compile qt_main.py qt_workbench.py
```

Expected: exit code 0.

If PySide6 is not installed, run `python -m pip install -r requirements.txt`. If this fails due network sandboxing, request escalation.

## Task 3: Build Product UI Skeleton

**Files:**

- Modify: `qt_workbench.py`
- Create: `qt_theme.py`

- [x] **Step 1: Define theme tokens**

Create `qt_theme.py` with restrained dark-neutral product UI values:

```python
APP_STYLESHEET = """
QMainWindow {
    background: #171a1f;
    color: #e6e8ec;
}
QFrame#SidePanel, QFrame#InspectorPanel {
    background: #20242b;
    border: 1px solid #303741;
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
QPushButton:pressed {
    background: #1f6f68;
}
QPushButton#PrimaryButton {
    background: #1f7a70;
    border-color: #2a9d8f;
}
"""
```

- [x] **Step 2: Build the main layout**

`AnnotationWorkbench` should contain:

- Top toolbar: source folder, target folder, key profile selector, presentation mode toggle.
- Left panel: file queue list.
- Center panel: image viewer placeholder.
- Right panel: profile classification buttons, progress, recent operation.
- Status bar: current file and keyboard hint.

- [x] **Step 3: Verify static UI opens**

Run:

```powershell
python qt_main.py
```

Expected: a Qt window opens with the workbench structure. No annotation behavior required yet.

Manual check: no overlapping labels, panels resize sensibly, toolbar actions are
grouped by workflow stage, and the image viewer occupies the dominant center
area.

## Task 4: Implement High-Performance Image Viewer

**Files:**

- Create: `qt_image_viewer.py`
- Modify: `qt_workbench.py`

- [x] **Step 1: Create viewer class**

Use `QGraphicsView` + `QGraphicsScene` + `QGraphicsPixmapItem`.

Required API:

```python
class ImageViewer(QGraphicsView):
    def load_image(self, path: Path) -> None: ...
    def fit_to_window(self) -> None: ...
    def reset_view(self) -> None: ...
```

Behavior:

- Wheel zoom transforms the view, not the original image data.
- Left mouse drag pans.
- Double click or toolbar action resets to fit.
- Decode images on a `QThread`/worker object, not on the UI thread.
- Load with `QImage` and detach decoded pixels from the source path before file
  move operations.
- Track a monotonically increasing load token or image path so stale loads are
  ignored when the user navigates before loading completes.
- Show visible loading feedback within 100 ms for large images.
- Never perform large image decoding on the UI thread.

- [x] **Step 2: Implement async loader and cancellation token**

Add a worker that accepts `(path, token)` and emits `(path, token, QImage,
error)`. `ImageViewer` should only display the result if the returned token
matches its latest requested token.

- [x] **Step 3: Wire viewer into center panel**

Replace placeholder center label with `ImageViewer`.

- [ ] **Step 4: Manual performance smoke**

Run:

```powershell
python qt_main.py
```

Open a large local image through a temporary debug action or direct call during development. Confirm wheel zoom and drag pan feel immediate.

Target: 12 to 24 MP images remain interactive during pan and wheel zoom; no
full-quality resample should run for every wheel event.

## Task 5: Wire Batch Workflow

**Files:**

- Modify: `qt_workbench.py`
- Use: `classifier_core.py`, `config_manager.py`, `binding_profiles.py`

- [x] **Step 1: Source folder selection**

Add action to choose a folder using `QFileDialog.getExistingDirectory`.

Behavior:

- `source_folder` is selected by user.
- `target_folder` defaults to `source_folder.parent`.
- `ClassifierSession.refresh()` scans images.
- File queue list populates with file names.
- First image loads in the viewer.

- [x] **Step 2: Target folder selection**

Add action to choose target folder independently.

- [x] **Step 3: Navigation**

Support next, previous, skip, refresh, and jump via list click.

- [x] **Step 4: Refresh action**

Add a visible refresh action and configured shortcut. Refresh must call the core
session refresh behavior and preserve current file/index according to the
behavior contract.

- [x] **Step 5: Progress and status**

Update progress after every scan, navigation, classify, and undo.

Expected visible fields:

- current index / total
- remaining count
- current file name
- active profile
- last operation summary

- [x] **Step 6: Recent operation history**

Show a short recent history list in the right panel. It should include at least
the latest move and undo operations with file name and target category/path
summary.

- [x] **Step 7: Error states**

Render non-blocking status/inline errors for:

- corrupt or unsupported image
- externally moved/deleted source file
- target folder permission failure
- move failure
- undo restore path already exists
- stale load ignored after navigation

## Task 6: Key Binding Profiles And Classification UI

**Files:**

- Modify: `qt_workbench.py`
- Use: `binding_profiles.py`, `shortcut_manager.py`

- [x] **Step 1: Profile selector**

Load `binding_profiles` from config using `normalize_binding_profiles`. Populate a `QComboBox`.

Behavior:

- Changing profile updates classification buttons and active key map.
- Active profile is saved to config.
- `default_key_bindings` stays synchronized with the active profile.

- [x] **Step 2: Classification buttons**

Render current profile bindings in the right panel as stable rows:

```text
[P] PT
[Q] QK
[G] GE
```

Each button triggers the same classification path as keyboard shortcuts.

- [x] **Step 3: Keyboard shortcuts**

Register:

- action shortcuts from `config["shortcuts"]`
- classification keys from active profile

Classification keys must not trigger while text inputs are focused.
Classification keys must also be disabled while combo popups, dialogs, and file
dialogs are active. Classification shortcuts should only be enabled when the
workbench or image viewer has focus.

If a classification key conflicts with a configured action shortcut, show a
warning before classification starts or give the conflict a documented priority.
Do not allow overlapping move operations from rapid key repeat.

- [x] **Step 4: Classification and undo**

Use `ClassifierSession.classify_current(key)` and `undo_last()`.

After classification:

- file moves to target category folder
- queue removes or advances from current image
- viewer shows next image
- last operation feedback updates without modal interruption

## Task 7: Presentation Mode

**Files:**

- Modify: `qt_workbench.py`
- Modify: `qt_theme.py`

- [x] **Step 1: Add toggle**

Presentation mode hides:

- file queue detail controls
- target/config editing controls
- recent operation details beyond last action

Presentation mode keeps:

- large image
- active classification buttons
- progress
- current folder/batch name
- live undo and classification shortcuts
- live navigation shortcuts

- [ ] **Step 2: Visual polish**

Use larger spacing and a cleaner right panel in presentation mode. Do not add a homepage, decorative particles, glassmorphism, or unrelated animation.

- [ ] **Step 3: Manual demo check**

Run:

```powershell
python qt_main.py
```

Expected: in under 30 seconds, an observer can understand current image, available classifications, and progress.

Check at 1200x800, 1920x1080, and Windows 150% scaling when possible. Text must
not clip or overlap.

## Task 8: Switch Default Entry Point After Feature Parity

**Files:**

- Modify: `main.py`
- Modify: `ImageClassifier.spec`
- Modify: `build.bat`

- [ ] **Step 1: Switch `main.py` to Qt**

After the Qt workbench can select folders, classify, undo, refresh, and persist profiles, update `main.py` to launch Qt.

Keep the old Tkinter implementation available as `image_classifier.py` for one release if useful, but do not route users through it.

- [ ] **Step 2: Update PyInstaller config**

Change hidden imports and excludes for PySide6. Remove Tkinter-specific assumptions once Qt is the default.

- [ ] **Step 3: Build smoke**

Run:

```powershell
.\build.bat
```

Expected: release folder contains the exe and config file. The exe launches the Qt workbench.

## Task 9: Verification Suite

**Files:**

- Modify: `tests/test_classifier_core.py`
- Modify: `tests/test_binding_profiles.py` only if profile behavior changes.

- [ ] **Step 1: Unit verification**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Compile verification**

Run:

```powershell
python -m py_compile main.py qt_main.py qt_workbench.py qt_image_viewer.py qt_theme.py classifier_core.py config_manager.py shortcut_manager.py binding_profiles.py
```

Expected: exit code 0.

- [ ] **Step 3: Manual functional smoke**

Use a disposable folder with copied images.

Verify:

- select source folder
- target defaults to parent
- choose active profile
- classify with keyboard
- classify with button
- undo restores latest moved file
- refresh handles externally removed files
- next/previous navigation works
- presentation mode toggles without losing current image

- [ ] **Step 4: Performance smoke**

Use a batch with 5,000 to 10,000 file entries. If a real dataset is unavailable,
generate disposable placeholder image files in a temporary folder.

Verify:

- file queue remains responsive
- loading feedback appears within 100 ms for large images
- first image loads without freezing the app for long periods
- wheel zoom and pan are visibly smoother than Tkinter
- keyboard classification updates queue/progress/history/next image within
  about 250 ms on local SSD, or shows non-blocking moving feedback if slower

- [ ] **Step 5: UI quality review**

Use this checklist instead of vague "premium" language:

- no clipped text at 1200x800, 1920x1080, and Windows 150% scaling
- no overlapping controls
- primary workflow controls are visible without hunting
- file move warnings are visible before classification starts
- empty/loading/error states are styled and understandable
- presentation mode hides editing complexity but keeps live workflow controls

- [ ] **Step 6: New-user flow checklist**

Have a tester or reviewer follow the UI without implementation notes. The flow
passes if they can identify and perform these actions in under 3 minutes:

- select source folder
- select or confirm key binding profile
- classify one image
- undo the move
- navigate to another image
- explain progress state

## Task 10: Documentation Update

**Files:**

- Modify: `README.md`
- Modify: `docs/specs/ui-redesign.md`

- [ ] **Step 1: README update**

Document:

- PySide6 dependency
- development run command
- packaging command
- key binding profile behavior
- warning that classification moves files

- [ ] **Step 2: Spec update**

Resolve the open questions in `docs/specs/ui-redesign.md` after implementation decisions are made:

- Qt image-viewing strategy: `QGraphicsView` / `QGraphicsScene` /
  `QGraphicsPixmapItem`
- packaged settings location: portable `config.json` beside the exe
- presentation mode shipped in first Qt version
- tested batch/image performance baseline

## Completion Criteria

The PySide6 rewrite is complete when:

- The Qt workbench is the default app entry point.
- The user can perform the full existing classification workflow.
- Key binding profiles persist and remain backward-compatible.
- Core file behavior is covered by unit tests.
- Manual smoke confirms no accidental file deletion or overwrite in normal flow.
- Image zoom/pan is visibly smoother than the current Tkinter canvas.
- Presentation mode exists as a workbench state, not a homepage.

## Current Implementation Notes

As of 2026-05-20:

- `qt_main.py` launches the PySide6 workbench as a parallel entry point.
- `main.py` still launches the existing Tkinter flow until packaging parity is
  reviewed.
- Core scanning, move, undo, refresh, and conflict behavior are covered by
  `tests/test_classifier_core.py`.
- Initial Qt workflow coverage lives in `tests/test_qt_workbench.py`, including
  profile migration persistence, shortcut conflict priority, queue rebuild
  avoidance during navigation, and non-blocking move dispatch.
- Image decoding reads file bytes into memory on a worker thread before Qt image
  decoding, avoiding Windows file-handle races with classification moves.
- File moves and undo run on a Qt worker thread with non-blocking status
  feedback.
- Remaining before default-entry switch: manual visual/performance smoke,
  packaging updates, build smoke, and documentation refresh.
