# Development Diagnostic Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add development-only file diagnostics that preserve enough Python, Qt, thread, image-load, HQ-resize, navigation, move, memory, and handle state to locate the repeated native `QThread` abort.

**Architecture:** A new `diagnostic_logging.py` module owns rotating JSON event logs, a separately flushed crash log, Python exception hooks, `faulthandler`, and the Qt message handler. `qt_main.py` enables it before `QApplication` only when running from source; `qt_image_viewer.py` and `qt_workbench.py` add observation-only events without changing existing branches, signal connections, cancellation, waits, or file operations.

**Tech Stack:** Python standard library `logging`, `logging.handlers`, `faulthandler`, `traceback`, `ctypes`, PySide6 `qInstallMessageHandler`, and `unittest`.

---

## Scope And Safety Constraints

- Development mode is `not getattr(sys, "frozen", False)`. Frozen/PyInstaller execution must not create logs or install diagnostic hooks.
- Do not modify `ImageClassifier.spec`, `build.bat`, classification behavior, image rendering behavior, or QThread ownership/lifetime.
- Do not add a `StreamHandler`; normal console output must remain unchanged and logging must go only to files.
- Worker-thread logging may call `threading.get_ident()` but must not call `QThread.currentThread()` or retain additional Qt wrappers.
- Logging failures must never stop navigation, image decode, resize, move, undo, or shutdown.
- Paths may contain Chinese characters and are written as UTF-8 JSON strings.
- `logs/` is ignored by Git. Files are:

```text
logs/
  ars-debug.log
  ars-debug.log.1
  ars-debug.log.2
  ars-debug.log.3
  ars-crash.log
```

- `ars-debug.log` rotates at 10 MiB with three backups. Default development level is `DEBUG`; `ARS_LOG_LEVEL` may override it with a standard logging level such as `INFO`.
- Every debug record is one JSON object with `timestamp`, `session_id`, `pid`, `python_thread_id`, `python_thread_name`, `logger`, `level`, `event`, and `fields`.
- `ars-crash.log` is append-only and is explicitly flushed and synchronized with `os.fsync()` after fatal/unhandled records.

## Event Contract

The event names below are stable diagnostic vocabulary. Fields that are unavailable must be omitted instead of guessed.

| Area | Events |
| --- | --- |
| Process | `app_start`, `app_stop`, `python_unhandled_exception`, `thread_unhandled_exception`, `qt_message`, `qt_fatal` |
| Navigation | `navigation_requested`, `current_image_load_requested` |
| Decode | `image_load_queued`, `image_load_coalesced`, `image_load_worker_start`, `image_bytes_read`, `image_decode_finished`, `image_load_result`, `image_load_thread_finished` |
| HQ resize | `hq_abort`, `hq_thread_pruned`, `hq_resize_skipped`, `hq_resize_worker_start`, `hq_lanczos_start`, `hq_lanczos_finished`, `hq_resize_cancelled`, `hq_resize_result`, `hq_resize_thread_finished` |
| File move | `move_thread_start`, `move_result`, `move_thread_finished` |
| Shutdown | `workbench_close_start`, `viewer_shutdown_start`, `viewer_shutdown_thread_wait`, `viewer_shutdown_finished`, `workbench_close_finished` |

Process metrics are added only at image-load completion, HQ start/finish, every tenth successful navigation, and shutdown. On Windows they include best-effort `working_set_bytes`, `private_bytes`, and `handle_count`; metric collection returns partial or empty data on failure and never raises.

### Task 1: Diagnostic Module Contract

**Files:**
- Create: `tests/test_diagnostic_logging.py`
- Create: `diagnostic_logging.py`

- [ ] **Step 1: Write the failing file-only logging tests**

Add `DiagnosticLoggingTest` cases that call `shutdown_diagnostics()` in setup/teardown and use a temporary log directory. The key assertions are:

```python
with patch.dict(os.environ, {"ARS_LOG_LEVEL": "DEBUG"}):
    configure_diagnostics(log_dir)
    log_event(get_logger("tests.diagnostics"), "probe", path=Path("样本.jpg"), token=17)

handlers = logging.getLogger("ars").handlers
self.assertTrue(handlers)
self.assertFalse(any(type(item) is logging.StreamHandler for item in handlers))

record = next(
    json.loads(line)
    for line in (log_dir / "ars-debug.log").read_text(encoding="utf-8").splitlines()
    if '"event":"probe"' in line
)
self.assertEqual(record["fields"], {"path": "样本.jpg", "token": 17})
```

- [ ] **Step 2: Write the failing crash-hook tests**

Verify that direct invocation of the installed handler is non-terminating in tests but records the fatal message and a Python thread dump:

```python
configure_diagnostics(log_dir)
_qt_message_handler(QtMsgType.QtFatalMsg, None, "fatal test marker")
shutdown_diagnostics()

text = (log_dir / "ars-crash.log").read_text(encoding="utf-8")
self.assertIn("fatal test marker", text)
self.assertIn("qt_fatal", text)
self.assertIn("Thread", text)
```

Also save `sys.excepthook` and `threading.excepthook`, assert configuration replaces them, and assert shutdown restores the same objects.

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```powershell
D:/miniforge3/envs/tool/python.exe -m unittest tests.test_diagnostic_logging -v
```

Expected: import failure because `diagnostic_logging.py` does not exist.

- [ ] **Step 4: Implement the minimal diagnostic module**

Expose this interface:

```python
def configure_diagnostics(log_dir: Path | None = None) -> None: ...
def get_logger(name: str) -> logging.Logger: ...
def log_event(logger: logging.Logger, event: str, level: int = logging.DEBUG, **fields) -> None: ...
def process_metrics() -> dict[str, int]: ...
def shutdown_diagnostics() -> None: ...
```

Implementation requirements:

```python
handler = RotatingFileHandler(
    debug_path,
    maxBytes=10 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
```

Use a custom formatter that serializes records with `json.dumps(..., ensure_ascii=False, separators=(",", ":"), default=str)`. Store the session id and structured fields on the record through `extra`. Make configuration and shutdown idempotent under a module lock.

Open `ars-crash.log` for append with UTF-8 line buffering. Install `sys.excepthook`, `threading.excepthook`, `faulthandler.enable(file=crash_stream, all_threads=True)`, and `qInstallMessageHandler(_qt_message_handler)`. Fatal and unhandled handlers write directly to the crash stream, call `faulthandler.dump_traceback(file=crash_stream, all_threads=True)`, then flush and `os.fsync()` before returning. Preserve and restore the prior Python and Qt hooks during shutdown.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run the focused command from Step 3. Expected: all diagnostic logging tests pass with no console log records.

### Task 2: Development Startup And Shutdown

**Files:**
- Modify: `qt_main.py:1-18`
- Test: `tests/test_diagnostic_logging.py`

- [ ] **Step 1: Add a failing frozen-mode gate test**

Patch `qt_main.configure_diagnostics`, set `sys.frozen = True`, patch the Qt application/workbench, call `main()`, and assert diagnostics were not configured. Add the inverse source-mode assertion.

- [ ] **Step 2: Run the startup tests and verify RED**

Expected: the configure mock is never called because startup integration is absent.

- [ ] **Step 3: Install diagnostics before `QApplication`**

Use this control structure without changing the window lifecycle:

```python
def main() -> int:
    diagnostics_enabled = not getattr(sys, "frozen", False)
    if diagnostics_enabled:
        configure_diagnostics()
    logger = get_logger("main")
    try:
        log_event(logger, "app_start", level=logging.INFO, ...)
        app = QApplication(sys.argv)
        config_manager = ConfigManager()
        window = AnnotationWorkbench(config_manager)
        window.show()
        exit_code = app.exec()
        log_event(logger, "app_stop", level=logging.INFO, exit_code=exit_code)
        return exit_code
    finally:
        if diagnostics_enabled:
            shutdown_diagnostics()
```

Include Python, PySide6, Qt and platform versions, PID, executable, config path, and log directory in `app_start`. `log_event` is a no-op when diagnostics are disabled.

- [ ] **Step 4: Run focused startup tests**

Expected: source mode configures and shuts down diagnostics; frozen mode does neither.

### Task 3: Image Decode And HQ Resize Call Chain

**Files:**
- Modify: `qt_image_viewer.py:1-136`
- Modify: `qt_image_viewer.py:193-290`
- Modify: `qt_image_viewer.py:319-446`
- Modify: `qt_image_viewer.py:530-596`
- Test: `tests/test_qt_workbench.py`

- [ ] **Step 1: Add failing lifecycle-event tests**

Patch `qt_image_viewer.log_event` and exercise one successful `_ImageLoadWorker.run`, one cancelled `_HqResizeWorker.run`, rapid coalesced `ImageViewer.load_image` calls, and `ImageViewer.shutdown`. Assert event names and tokens, not call counts or ordering between unrelated threads.

- [ ] **Step 2: Run the viewer tests and verify RED**

Expected: event assertions fail because no call-chain instrumentation exists.

- [ ] **Step 3: Instrument workers with duration and result state**

At worker entry capture `started = time.perf_counter()` and `python_thread_id = threading.get_ident()`. Log before and after file read/decode and LANCZOS, including token, path, byte count, source/target dimensions, cancellation stage, error text, and `duration_ms`. Use `logger.exception` only inside existing `except` blocks; do not add new Qt calls.

- [ ] **Step 4: Instrument viewer thread ownership**

Set diagnostic Qt names without retaining new objects:

```python
thread.setObjectName(f"image-load-{token}")
thread.setObjectName(f"hq-resize-{token}")
```

Log before `thread.start()`, in the existing result slots, in both existing finished handlers, when loads are coalesced, when HQ work is cancelled/pruned/skipped, and around every shutdown wait. Include `_load_token`, `_hq_token`, active token lists, pending token/path, `thread.objectName()`, `thread.isRunning()` when safe, and selected process metrics at the bounded points defined above.

- [ ] **Step 5: Run viewer tests and verify GREEN**

Run:

```powershell
D:/miniforge3/envs/tool/python.exe -m unittest tests.test_qt_workbench.QtWorkbenchTest.test_viewer_coalesces_rapid_load_requests_to_latest_image tests.test_qt_workbench.QtWorkbenchTest.test_viewer_abort_hq_cancels_the_active_worker tests.test_qt_workbench.QtWorkbenchTest.test_viewer_shutdown_waits_for_running_image_worker -v
```

Expected: all selected tests pass and event assertions see a complete token lifecycle.

### Task 4: Navigation, Move, And Close Call Chain

**Files:**
- Modify: `qt_workbench.py:1-182`
- Modify: `qt_workbench.py:690-767`
- Modify: `qt_workbench.py:1216-1318`
- Modify: `qt_workbench.py:1557-1618`
- Test: `tests/test_qt_workbench.py`

- [ ] **Step 1: Add failing workbench event tests**

Patch `qt_workbench.log_event`, navigate across images, complete one move callback, clear its thread, and close a workbench. Assert `navigation_requested`, `current_image_load_requested`, `move_thread_start`, `move_result`, `move_thread_finished`, and the two close boundary events include the expected paths/tokens/status.

- [ ] **Step 2: Run the workbench tests and verify RED**

Expected: missing event assertions fail.

- [ ] **Step 3: Add observation-only workbench events**

Add `_navigation_count = 0` in `AnnotationWorkbench.__init__`. In `_set_current_image_index`, log source/target index and path immediately before the existing assignment; increment the counter only after validation succeeds and add metrics every tenth navigation. In `_load_current_image`, log whether the image is empty, unchanged, or passed to the viewer.

In `_run_move_operation`, name the thread `file-move`, log operation/callback names before `start()`, log result/error in the existing completion handlers, and log thread cleanup in `_clear_move_thread`. In `closeEvent`, log before and after the existing move-thread wait and viewer shutdown. Do not reorder any existing statement except inserting adjacent `log_event` calls.

- [ ] **Step 4: Run focused workbench tests and verify GREEN**

Expected: navigation, move, and close tests pass with unchanged UI/session assertions.

### Task 5: Ignore Runtime Logs And Verify End To End

**Files:**
- Modify: `.gitignore`
- Verify: all source and test files above

- [ ] **Step 1: Ignore generated logs**

Add exactly:

```gitignore
# Development diagnostics
logs/
```

- [ ] **Step 2: Compile changed Python files**

Run:

```powershell
D:/miniforge3/envs/tool/python.exe -m py_compile diagnostic_logging.py qt_main.py qt_image_viewer.py qt_workbench.py tests/test_diagnostic_logging.py
```

Expected: exit code 0 and no output.

- [ ] **Step 3: Run the full regression suite**

Run:

```powershell
D:/miniforge3/envs/tool/python.exe -m unittest discover -s tests -v
```

Expected: all existing 112 tests plus new diagnostics tests pass.

- [ ] **Step 4: Run an offscreen navigation stress check**

Create temporary valid images, run the Qt workbench offscreen, switch at least 100 times while processing events, allow worker completion, then close normally. Assert:

- process exits with code 0;
- `ars-debug.log` contains the final navigation token and matching load thread finish;
- `ars-crash.log` contains no `qt_fatal` for the normal run;
- no `QThread: Destroyed while thread is still running` text appears;
- debug log contains memory/handle snapshots before and after the loop.

- [ ] **Step 5: Run GitNexus change detection and inspect scope**

Run `detect_changes({scope: "compare", base_ref: "main", repo: "ARS"})`. Expected changed scope is limited to startup, viewer load/HQ, navigation/move/close paths, tests, the new diagnostics module, and `.gitignore`. Any additional production flow must be explained or removed.

## Acceptance Criteria

- Source execution creates rotating `logs/ars-debug.log` and append-only `logs/ars-crash.log`; frozen execution creates neither.
- No logging handler writes ordinary event logs to stdout/stderr.
- A directly simulated Qt fatal message produces its text, session/PID/thread metadata, and an all-thread Python traceback in `ars-crash.log` before returning to Qt.
- Rapid navigation can be reconstructed by token from workbench request through decode worker start/result and QThread finish.
- HQ cancellation can be reconstructed without any call to `QThread.currentThread()`.
- Move and application shutdown waits are visible in the same session timeline.
- Logging failures are swallowed at the diagnostic boundary and do not alter application behavior.
- Existing 112 tests and all new tests pass; the offscreen 100-navigation stress run exits normally.
- No packaging files are changed and `logs/` is not tracked by Git.

## Self-Review

- Spec coverage: file-only logging, rotation, fatal persistence, Python/Qt hooks, process metrics, all identified call-chain boundaries, development-only gating, packaging exclusion, and verification all map to explicit tasks.
- Placeholder scan: the plan contains no deferred implementation markers; event names, interfaces, files, commands, and expected results are explicit.
- Type consistency: the module API and event names are identical across tests, startup, viewer, workbench, and acceptance criteria.
