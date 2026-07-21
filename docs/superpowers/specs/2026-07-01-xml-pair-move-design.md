# XML Pair Move Mode Design

## Context

ARS is a Windows local image annotation workbench. The current mainline is the
PySide6 Qt workbench backed by `classifier_core.py`. Classification moves the
current image into `Target\<category>\`, avoids overwriting target files by
appending numeric suffixes, removes the image from the queue, and supports
session-only undo.

Some source folders already contain manual annotation labels where an image and
its Pascal/VOC-style XML file sit side by side:

```text
xx.jpg
xx.xml
```

The new feature adds an optional mode that moves the matching XML label together
with the classified image. The default behavior must stay unchanged.

## Goals

- Add a user-facing mode button for moving a matching XML label with the image.
- Keep the mode off by default so existing workflows still move only images.
- When the mode is on, move `image_stem.xml` from the image's source folder into
  the same target category folder as the image.
- If the matching XML file does not exist, classify normally and move only the
  image.
- If the image target name changes because of a conflict, rename the XML to the
  same resulting stem.
- Avoid overwriting either the target image or target XML.
- Include moved XML files in undo.

## Non-Goals

- Do not move XML files in default mode.
- Do not persist this mode in `config.json` for this change.
- Do not scan XML files into the image queue.
- Do not parse, validate, or edit XML contents.
- Do not add recursive source scanning.
- Do not update the old Tkinter classifier unless a later task explicitly asks
  for legacy UI parity.

## User Interaction

The Qt workbench will add a small checkable button in the right inspector near
the `Classify` header, alongside the existing classify layout density control.

Initial state:

- Off on every app start.
- The button text should be short, for example `XML`.
- The tooltip should make the behavior explicit, for example
  `Move matching .xml with image`.

When off, classification is identical to the current behavior.

When on, any classification key or classify button uses XML pair move semantics.
The same mode affects undo records created while it was enabled.

## Core Behavior

### Classification Without XML

Given:

```text
Source\a.jpg
```

When XML pair mode is enabled and the user classifies with `p -> PT`, the result
is:

```text
Target\PT\a.jpg
```

No error or warning is required because missing XML is allowed.

### Classification With XML

Given:

```text
Source\a.jpg
Source\a.xml
```

When XML pair mode is enabled and the user classifies with `p -> PT`, the result
is:

```text
Target\PT\a.jpg
Target\PT\a.xml
```

The source folder no longer contains either file.

### Target Name Conflicts

The image and XML must keep matching stems after conflict resolution.

Given:

```text
Source\a.jpg
Source\a.xml
Target\PT\a.jpg
```

The result is:

```text
Target\PT\a_1.jpg
Target\PT\a_1.xml
```

If `Target\PT\a_1.xml` already exists, the implementation must continue looking
for a fully safe pair name, for example:

```text
Target\PT\a_2.jpg
Target\PT\a_2.xml
```

It must not overwrite an existing image or XML file.

## Undo Behavior

`MoveRecord` should record optional XML source and target paths when XML was
moved.

Undo rules:

- If the move record has no XML paths, undo remains image-only.
- If the move record has XML paths, undo restores both the image and XML.
- Undo must refuse to overwrite an existing original image path.
- Undo must refuse to overwrite an existing original XML path.
- If a moved XML target is missing when undo runs, undo fails with a clear
  classification core error instead of guessing a replacement.

This keeps undo conservative for destructive filesystem operations.

## Architecture

### `classifier_core.py`

Extend the core session because file movement, conflict naming, and undo are
shared behavior and are already tested there.

Planned changes:

- Add XML-pair mode state to `ClassifierSession`, defaulting to `False`.
- Extend `MoveRecord` with optional XML source and target paths.
- Add a pair-aware target resolver used only when XML mode is enabled and the
  source XML exists.
- Move the image first and the XML second within the same core operation.
- If XML movement fails after the image moved, attempt to restore the image to
  its original source path before raising a move failure. If rollback cannot be
  completed, raise the original failure with enough context for the UI to show
  the problem.

### `qt_workbench.py`

The Qt workbench owns the mode toggle and passes the current mode into the active
`ClassifierSession`.

Planned changes:

- Add a checkable XML mode button near the `Classify` header (`LinkXML` switch).
- Default the button and session mode to off when config omits the field.
- When toggled, update the current session's XML mode if a session exists, and
  persist `image_classifier.move_xml_pairs` to config for the next launch.
- When creating a new session after selecting a source folder, seed it from the
  current button state.
- Keep presentation mode simple: it may hide the XML mode button along with the
  profile/history controls, but classification should continue using the last
  selected mode.
- Include an XML marker in recent move text only when an XML was actually moved.
  A suitable format is `p -> PT + XML: a.jpg`.

## Error Handling

- Missing matching XML is not an error.
- Existing target image or XML names are handled by choosing a safe matching
  pair stem.
- Image move failure keeps current behavior: report the core error and do not
  update queue state.
- XML move failure after image move should rollback the image when possible and
  report a core error.
- Undo conflicts are reported through existing UI error handling.

## Tests

Core tests in `tests/test_classifier_core.py` should cover:

- Default mode leaves matching XML in the source folder.
- XML mode moves image and matching XML together.
- XML mode moves only the image when XML is missing.
- Image target conflict renames both image and XML to the same new stem.
- XML target conflict advances to a safe pair stem without overwriting.
- Undo restores both image and XML.
- Undo refuses to overwrite an existing original XML file.

Workbench tests in `tests/test_qt_workbench.py` should cover:

- XML mode button exists and is off by default.
- Toggling the button updates the current session.
- Toggling the button persists `move_xml_pairs` and restores after restart.
- New sessions inherit the current button state.

## Verification

Run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest discover -s tests -v
```

Also run the compile check when implementation touches Python modules:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m py_compile qt_main.py qt_workbench.py qt_image_viewer.py qt_theme.py classifier_core.py config_manager.py binding_profiles.py
```
