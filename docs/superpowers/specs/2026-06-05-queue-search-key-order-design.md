# Queue Search And Key Order Design

## Context

ARS is currently maintained on the Qt workbench path:

- `qt_main.py` launches the app.
- `qt_workbench.py` owns the main UI, queue state, shortcuts, profile editing,
  and config persistence.
- `classifier_core.py` owns file scanning, move, conflict naming, and undo.
- `binding_profiles.py` normalizes profile config and keeps the active profile
  synchronized with `default_key_bindings`.

This design adds two UI features without changing file move semantics.

## Goals

1. Add a queue filename search above the left file list.
2. Add a single-step `Back` button that returns to the previous image position.
3. Allow users to reorder key mapping rows in the `Keys` dialog by dragging.
4. Persist key mapping order only after the user clicks `Save`.

## Non-Goals

- No recursive search.
- No fuzzy or partial filename search.
- No queue filtering.
- No multi-level navigation history.
- No changes to image classification, move, conflict naming, or undo behavior.
- No migration away from the existing `config.json` profile structure.

## Queue Search And Back

### UI

In the left `Queue` panel, add a compact control row between the queue header
and `queue_list`:

- A `Search` input with placeholder text `Filename`.
- A `Back` button matching the existing short action button style.

The search input triggers when the user presses Enter.

### Matching Rule

The user must enter the complete filename, including extension. Matching is
case-insensitive and compares against `Path.name` for each item in the current
session queue.

Examples:

- `a.jpg` matches `A.JPG`.
- `a` does not match `a.jpg`.
- `a.jp` does not match `a.jpg`.

### Navigation History

The workbench stores one previous image path, not a stack. The previous image is
updated before successful navigation changes caused by:

- search by filename
- clicking an item in the queue list
- jumping by index
- next image
- previous image
- skip, because it delegates to next image

The previous image is recorded only when there is a current image and the target
image is different from it.

### Search Behavior

When Enter is pressed in the search input:

1. If there is no active session or no images, show a status message and keep
   the current position.
2. Search the current queue by complete filename, case-insensitive.
3. If no match is found, keep the current position and show a status message.
4. If a match is found, record the previous image path, update
   `session.current_index`, and reuse the existing session synchronization path
   so the queue selection, viewer, jump box, progress, and status widgets stay
   consistent.

### Back Behavior

When `Back` is clicked:

1. If no previous image path is stored, show a status message.
2. If the stored image path is no longer in the current queue, keep the current
   position, clear the stale previous image path, and show a status message that
   the previous image is no longer available.
3. If the stored image is present, swap the current image and previous image so
   a second `Back` returns to the image the user just left.
4. Reuse the existing session synchronization path.

This remains single-step history while still allowing the user to toggle between
the current and previous positions.

## Key Mapping Drag Order

### UI

The `Keys` dialog keeps the existing editing behavior:

- one key input
- one target folder input
- one `Delete` button per row
- `Add Mapping`
- `Save` and `Cancel`

Each row gains a drag handle at the left. Dragging a row changes only the
temporary order inside the dialog.

### Save And Cancel

Clicking `Save` reads rows in their current visual order and rebuilds the active
profile mapping in that order.

Clicking `Cancel` discards all edits, including row order changes.

Empty rows remain allowed while editing. On save, rows where both key and folder
are empty are ignored, matching the current dialog behavior.

Validation stays the same:

- a saved row must have exactly one key character
- a saved row must have a non-empty target folder
- duplicate keys are rejected

### Persistence

After `Save`, the new order is persisted through the existing
`update_active_bindings()` path:

- `image_classifier.binding_profiles[active_profile]`
- `image_classifier.default_key_bindings`
- `image_classifier.active_binding_profile`

Because Python dictionaries preserve insertion order, no additional schema field
is required.

### Runtime Effects

After saving:

- right-side `Classify` buttons render in the saved order
- classification shortcut registration follows the saved order
- future openings of the `Keys` dialog show the saved order

## Architecture

All UI work belongs in `qt_workbench.py`.

No changes are expected in `classifier_core.py` because scanning and moving are
unchanged.

No changes are expected in `binding_profiles.py` unless implementation reveals
that normalization is reordering mappings. The intended behavior is to preserve
dict insertion order.

## Testing

Add focused tests in `tests/test_qt_workbench.py`:

1. Filename search jumps to an exact case-insensitive match.
2. Filename search does not move when no file matches and reports status.
3. `Back` returns after search, list click, index jump, next, previous, and skip.
4. `Back` reports unavailable when the previous image is no longer in the queue.
5. Reordering mapping rows and saving persists the new profile order.
6. Cancelling the `Keys` dialog leaves persisted order unchanged.
7. `Add Mapping` appends a new row after existing rows.
8. Row deletion still removes without confirmation.

Full verification should run:

```powershell
& 'D:/miniforge3/envs/tool/python.exe' -m unittest discover -s tests -v
```

## Risks

- Queue navigation already has several entry points. The implementation should
  centralize "record previous then navigate" to avoid inconsistent `Back`
  behavior.
- The current key dialog uses a `QGridLayout`; drag reordering may be cleaner if
  rows are represented as row widgets in a vertical layout. That refactor should
  stay local to the dialog builder.
- Stale previous image paths are expected after classification or refresh. The
  UI should report this clearly without guessing a replacement target.
