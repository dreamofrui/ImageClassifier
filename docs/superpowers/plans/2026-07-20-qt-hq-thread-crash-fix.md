# Qt HQ Thread Crash Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent the Qt image viewer from aborting after repeated navigation by removing temporary `QThread.currentThread()` wrappers from the HQ worker cancellation path.

**Architecture:** Keep the existing single in-flight HQ job, token-based stale-result rejection, and Pillow LANCZOS output. Give each HQ worker a `threading.Event` cancellation flag that the UI thread sets without creating or destroying Qt thread wrappers in the worker thread.

**Tech Stack:** Python 3.11, PySide6, Pillow, `unittest` with the offscreen Qt platform.

---

### Task 1: Reproduce The Unsafe Cancellation Contract

**Files:**
- Modify: `tests/test_qt_workbench.py`

- [ ] Add a test that cancels `_HqResizeWorker`, replaces the module-level `QThread` with a sentinel that rejects `currentThread()`, and expects one `cancelled` result.
- [ ] Run the focused test and verify it fails because `_HqResizeWorker.cancel()` does not exist.

### Task 2: Replace Qt Thread Introspection With A Python Event

**Files:**
- Modify: `qt_image_viewer.py`
- Test: `tests/test_qt_workbench.py`

- [ ] Import `threading` and create one `threading.Event` per HQ worker.
- [ ] Add `_HqResizeWorker.cancel()` to set the event.
- [ ] Replace both `QThread.currentThread().isInterruptionRequested()` checks with the event.
- [ ] In `_prune_hq_threads(request_stop=True)`, call `worker.cancel()` before asking the thread event loop to quit.
- [ ] Run the focused test and existing HQ tests.

### Task 3: Stress And Regression Verification

**Files:**
- Modify only if a failing test exposes another defect.

- [ ] Run the full unit suite.
- [ ] Run an offscreen subprocess that performs at least 120 rapid workbench navigation operations with HQ settle overlap.
- [ ] Verify the subprocess exits with code 0 and all tracked worker dictionaries drain.
- [ ] Compile the Qt entry point and viewer/workbench modules.

