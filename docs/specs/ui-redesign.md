# ARS Image Annotation Workbench UI Redesign Spec

## 1. Problem Statement

The primary user is an annotator who processes image batches for long periods.
The secondary use case is occasional internal demonstration to leadership.

The current Tkinter interface feels like a temporary script: controls are stacked
without a clear workspace structure, status is hard to scan, and the visual
quality is not suitable for demos. Image zooming and panning also feel sluggish,
which breaks the flow of repeated annotation work.

The redesign must focus on the existing local image annotation product only.
LLM chat, TTS voice, and image generation are explicitly outside this product
and should not appear in this spec.

## 2. Solution Description

The application should become a batch annotation workbench centered on a large,
high-performance image preview.

Recommended layout:

- Left panel: image queue. The first version may use a file-name list. Thumbnail
  preview is optional and can be added later if performance allows.
- Center panel: large image preview. It supports smooth zoom, pan, fit-to-window,
  and reset view.
- Right panel: active key binding profile, classification targets, progress
  summary, and recent operation history.
- Bottom/status area: keyboard hints, current file details, and transient
  operation feedback.

The normal workflow should be:

1. Select a source folder.
2. Confirm or select the key binding profile.
3. Enter the annotation workbench.
4. Classify primarily with keyboard shortcuts.
5. Move through images continuously.
6. Undo, refresh, or jump when needed.

The workbench should also include a presentation mode. Presentation mode is not
a home page and not a separate marketing screen. It is a simplified state of the
real workbench: hide complex controls, keep the large image, classification
actions, current progress, and polished feedback visible. The user must be able
to return to the full workbench with one action.

## 3. Technical Constraints

The UI rewrite should use PySide6 / Qt rather than Tkinter.

Reasons:

- It keeps the project as a Python desktop application.
- It is better suited to polished desktop layouts, keyboard workflows, async
  image loading, and high-performance image viewing.
- It is lighter and more direct for local file operations than Electron.

Performance requirements:

- Image loading and decoding must not block the UI thread.
- Zooming and panning should use efficient view transforms or downsampled
  representations instead of full high-quality image resampling on every wheel
  event.
- The image viewer should use `QGraphicsView`, `QGraphicsScene`, and
  `QGraphicsPixmapItem` for the first Qt version.
- The viewer must detach decoded image data from the source file before move
  operations, so classification is not blocked by open file handles.
- Stale image loads must be ignored or cancelled when the user navigates before
  loading completes.
- The file queue must remain usable for large batches.
- Thumbnails are optional. If they are not performant enough for the first
  version, use a file-name list.
- The app should preserve existing local file behavior: classification moves
  files into target folders, and undo restores the latest move when possible.

Packaging considerations:

- The result must remain packageable as a Windows exe.
- Configuration and key binding profiles must continue to persist between runs.
- For this UI rewrite, keep the current portable configuration model:
  `config.json` lives beside the exe in the release folder. AppData-based
  settings migration is deferred to a later packaging hardening spec.
- Release documentation must warn users not to overwrite their edited
  `config.json` when upgrading the portable folder.

## 4. Existing Behavior Contract

The Qt rewrite must preserve these current behaviors unless a later spec
explicitly changes them:

- Source folder scanning is non-recursive. Only direct child files are included.
- Supported formats come from `image_classifier.supported_formats`.
- File matching is case-insensitive by extension.
- Image order is stable sorted path order.
- Selecting a source folder defaults the target folder to the source folder's
  parent directory.
- Users can manually change the target folder for subsequent classification.
- Classification creates the target category folder lazily when the user
  classifies the first image for that category.
- If the target file name already exists, append `_1`, `_2`, and so on before
  the extension.
- Classification moves files, not copies them.
- After classification, the moved file is removed from the queue. If the current
  index passes the end of the list, it moves to the last remaining image.
- Undo is session-only and last-in-first-out. It restores the latest moved file
  and inserts it back at the current index, not necessarily its original sorted
  position.
- Refresh rescans the source folder. If the current file still exists, keep it
  selected; otherwise keep the current index when possible and clamp to the
  queue bounds.
- Key binding profiles must remain compatible with `binding_profiles.py`:
  `binding_profiles`, `active_binding_profile`, and synchronized
  `default_key_bindings` are all preserved.

## 5. Keyboard And Error Model

Keyboard rules:

- Classification keys are active only while the workbench/image area has focus.
- Classification keys must not fire while a text input, combo popup, or file
  dialog interaction is active.
- If a classification key conflicts with a navigation or action shortcut, the UI
  must either warn the user or define a clear priority before enabling
  classification.
- Rapid key repeat must not trigger overlapping file moves. Move operations are
  serialized.
- Presentation mode keeps the same classification, undo, and navigation
  shortcuts as the full workbench.

Required non-blocking error states:

- Corrupt or unsupported image file.
- Current source file was moved or deleted externally.
- Target folder cannot be created or written.
- File move fails.
- Undo target source path already exists.
- Image load finishes after the user has navigated to another image.

Recent operation history:

- The full workbench should show a short visible list of recent moves and
  undo actions, not only a single last-action label.
- Presentation mode may collapse this to one concise latest-action summary.

## 6. Explicit Non-Goals

The first version will not include:

- AI automatic classification.
- Model training.
- Cloud sync.
- Multi-user collaboration.
- Complex analytics dashboards.
- A marketing-style home page.
- 3D effects, particles, glassmorphism, or decorative animation.
- Presentation mode as a separate landing page.
- Thumbnail generation as a hard requirement.
- AppData settings migration.

The first version must preserve:

- Source folder selection.
- Target folder selection.
- Key binding profile selection.
- Keyboard classification.
- File-moving classification behavior.
- Undo.
- Refresh.
- Progress feedback.
- Presentation mode as a workbench state.

## 7. Success Criteria

Annotation efficiency is successful when:

- A new user can understand the core flow within 3 minutes: select folder,
  choose key binding profile, classify, undo, and navigate.
- A trained user can annotate continuously with keyboard-first operation.
- Large batches do not lose state or accidentally move files to the wrong target.
- Zooming and panning feel clearly smoother than the current Tkinter version.
- A folder containing 5,000 to 10,000 image files can render a usable file-name
  queue without thumbnail generation as a requirement.
- Loading a large local image shows visible loading feedback within 100 ms and
  does not freeze input.
- Zoom and pan remain interactive on 12 to 24 MP images, targeting at least 30
  fps during drag and wheel interactions.
- Keyboard classification updates the queue, progress, history, and next image
  within about 250 ms on a local SSD, or shows non-blocking moving feedback if
  the move takes longer.

Leadership demo quality is successful when:

- The first impression is a formal internal product, not a temporary script.
- A viewer can understand within 30 seconds what image is being annotated, where
  it is being classified, and how progress changes.
- Classification feedback is visible, polished, and non-blocking.
- The interface feels premium through structure, spacing, typography, color,
  and responsiveness, not decorative effects.
- The demo flow works at 1200x800, 1920x1080, and Windows 150% scaling without
  clipped text or overlapping controls.
- Presentation mode toggles in and out with one action, keeps live
  classification, undo, and progress visible, and does not feel like a separate
  page.

## 8. Design Direction

Use the available local design guidance as follows:

- `impeccable`: define the product UI direction. The design should feel polished,
  restrained, task-focused, and credible in front of leadership.
- `frontend-ui-engineering`: define interaction quality. Keyboard flow, state
  feedback, component consistency, performance, and accessibility matter more
  than decoration.

The visual register is product UI, not brand or marketing UI. The interface
should serve the annotation task.

Recommended design principles:

- Prefer a professional workbench over a landing page.
- Use a restrained palette. Accent color should mark active selection, primary
  actions, and status only.
- Avoid generic AI-looking gradients, glass panels, oversized cards, and
  decorative motion.
- Use consistent controls and predictable layout.
- Motion should communicate state changes only, such as classification success,
  undo restoration, loading, or panel reveal.
- Presentation mode should be cleaner and more impressive, but still be the real
  product experience.

## 9. Implementation Decisions And Open Questions

- Use `QGraphicsView` / `QGraphicsScene` / `QGraphicsPixmapItem` for the first
  Qt image viewer.
- Presentation mode is part of the first Qt rewrite.
- V1 uses a file-name queue. Thumbnail preview is optional later.
- Should a later packaging hardening spec migrate portable `config.json`
  settings to AppData?
- What exact batch and image fixture set will be used for repeatable performance
  testing?
