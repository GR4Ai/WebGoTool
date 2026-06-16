"""BrowserWorker — QObject thread bridge between Playwright operations and Qt UI.

Runs all Playwright (sync) operations in a dedicated QThread.
Communicates with the main thread exclusively via Qt signals/slots.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot, QTimer

logger = logging.getLogger(__name__)


class BrowserWorker(QObject):
    """Thread-safe bridge: owns ChromeManager, EventRecorder, WorkflowRunner.

    All Playwright operations run through slots invoked from the main thread.
    Results are emitted back to the main thread via signals.
    """

    # ── Qt Signals (emitted → main thread) ──

    log_signal = Signal(str)
    error_signal = Signal(str)
    connected = Signal()
    disconnected = Signal()
    step_recorded = Signal(dict)
    element_hovered = Signal(dict)
    element_captured = Signal(dict)
    capture_cancelled = Signal()
    playback_step_start = Signal(int, dict)
    playback_step_done = Signal(int, bool, str)
    playback_finished = Signal(bool)

    def __init__(self):
        super().__init__()
        self._chrome_manager = None
        self._recorder = None
        self._runner = None
        self._page = None
        self.is_connected = False
        self._poll_timer = None  # Created after moveToThread, in connect_browser

    # ═══════════════════════════════════════════════════════════
    # Browser Connection
    # ═══════════════════════════════════════════════════════════

    @Slot()
    def connect_browser(self):
        """Launch/connect Chrome and set up the page reference."""
        from browser.chrome_manager import ChromeManager

        try:
            self._chrome_manager = ChromeManager()

            if not self._chrome_manager.launch_chrome():
                self.error_signal.emit("Failed to launch Chrome")
                return

            if not self._chrome_manager.connect_cdp():
                self.error_signal.emit("Failed to connect to Chrome via CDP")
                return

            self._page = self._chrome_manager.page
            self.is_connected = True

            # Create polling timer in THIS thread (worker thread, after moveToThread)
            if self._poll_timer is None:
                self._poll_timer = QTimer()
                self._poll_timer.setInterval(200)
                self._poll_timer.timeout.connect(self._poll_playwright)
                self._poll_timer.start()

            self.connected.emit()
            self.log_signal.emit(f"Connected to Chrome — {self._page.url}")

        except Exception as e:
            logger.exception("connect_browser failed")
            self.error_signal.emit(f"Browser connection error: {e}")

    @Slot()
    def disconnect_browser(self):
        """Clean shutdown of browser connection."""
        if self._chrome_manager:
            self._chrome_manager.close()
        self._page = None
        self.is_connected = False
        self.disconnected.emit()

    def _refresh_page(self):
        """Refresh the page reference (user may have switched tabs)."""
        if self._chrome_manager:
            new_page = self._chrome_manager.refresh_page()
            if new_page:
                self._page = new_page

    # ═══════════════════════════════════════════════════════════
    # Recording
    # ═══════════════════════════════════════════════════════════

    @Slot()
    def start_recording(self):
        """Inject recording JS into the current page."""
        if not self.is_connected or not self._page:
            self.error_signal.emit("Not connected to Chrome")
            return

        try:
            self._refresh_page()
            from recorder.event_recorder import EventRecorder

            self._recorder = EventRecorder(self._page)
            self._recorder.on_step_recorded = self._on_recorder_step
            self._recorder.on_log = lambda msg: self.log_signal.emit(msg)
            self._recorder.on_error = lambda msg: self.error_signal.emit(msg)
            self._recorder.start_recording()
            self.log_signal.emit("Recording started — interact with the page")

        except Exception as e:
            logger.exception("start_recording failed")
            self.error_signal.emit(f"Recording error: {e}")

    @Slot()
    def stop_recording(self):
        """Remove recording JS, clean up."""
        if self._recorder:
            try:
                steps = self._recorder.stop_recording()
                self.log_signal.emit(f"Recording stopped — {len(steps)} steps captured")
            except Exception as e:
                self.log_signal.emit(f"Stop recording error: {e}")
            self._recorder = None

    def _on_recorder_step(self, step):
        """Callback from EventRecorder → emit Qt signal."""
        self.step_recorded.emit(step.to_dict() if hasattr(step, "to_dict") else step)

    # ═══════════════════════════════════════════════════════════
    # Element Capture
    # ═══════════════════════════════════════════════════════════

    @Slot()
    def start_capture_mode(self):
        """Inject element capture overlay into the page."""
        if not self.is_connected or not self._page:
            self.error_signal.emit("Not connected to Chrome")
            return

        try:
            self._refresh_page()
            from recorder.event_recorder import EventRecorder

            # Create or reuse event recorder for capture
            if self._recorder is None:
                self._recorder = EventRecorder(self._page)
                self._recorder.on_log = lambda msg: self.log_signal.emit(msg)
                self._recorder.on_error = lambda msg: self.error_signal.emit(msg)

            # Wire capture callbacks
            self._recorder.on_hover = self._on_capture_hover
            self._recorder.on_capture = self._on_capture_confirm
            self._recorder.on_cancel = self._on_capture_cancel

            self._recorder.inject_capture_overlay()
            self.log_signal.emit("Capture mode ON — click element, Esc to cancel")

        except Exception as e:
            logger.exception("start_capture_mode failed")
            self.error_signal.emit(f"Capture error: {e}")

    @Slot()
    def stop_capture_mode(self):
        """Remove capture overlay."""
        if self._recorder:
            try:
                self._recorder.remove_capture_overlay()
                self.log_signal.emit("Capture mode OFF")
            except Exception as e:
                self.log_signal.emit(f"Capture cleanup error: {e}")

    def _on_capture_hover(self, element_info: dict):
        self.element_hovered.emit(element_info)

    def _on_capture_confirm(self, element_info: dict):
        self.element_captured.emit(element_info)

    def _on_capture_cancel(self):
        self.capture_cancelled.emit()

    # ═══════════════════════════════════════════════════════════
    # Playback
    # ═══════════════════════════════════════════════════════════

    @Slot(dict)
    def run_workflow(self, workflow_dict: dict):
        """Load and execute a workflow."""
        if not self.is_connected or not self._page:
            self.error_signal.emit("Not connected to Chrome")
            return

        try:
            self._refresh_page()
            from player.workflow_runner import WorkflowRunner

            self._runner = WorkflowRunner(self._page)
            self._runner.on_step_start = self._on_playback_step_start
            self._runner.on_step_complete = self._on_playback_step_complete
            self._runner.on_log = lambda msg: self.log_signal.emit(msg)
            self._runner.on_error = lambda msg: self.error_signal.emit(msg)
            self._runner.on_done = lambda ok: self.playback_finished.emit(ok)

            self._runner.load_workflow_dict(workflow_dict)
            self.log_signal.emit(f"Running workflow with {len(workflow_dict.get('steps', []))} steps")
            self._runner.execute()

        except Exception as e:
            logger.exception("run_workflow failed")
            self.error_signal.emit(f"Playback error: {e}")
            self.playback_finished.emit(False)

    @Slot()
    def stop_workflow(self):
        """Request the runner to stop."""
        if self._runner:
            self._runner.stop()

    @Slot()
    def pause_workflow(self):
        if self._runner:
            self._runner.pause()

    @Slot()
    def resume_workflow(self):
        if self._runner:
            self._runner.resume()

    def _on_playback_step_start(self, index: int, step):
        step_dict = step.to_dict() if hasattr(step, "to_dict") else step
        self.playback_step_start.emit(index, step_dict)

    def _on_playback_step_complete(self, index: int, step, success: bool, message: str):
        self.playback_step_done.emit(index, success, message)

    # ═══════════════════════════════════════════════════════════
    # Lifecycle
    # ═══════════════════════════════════════════════════════════

    def _poll_playwright(self):
        """Periodically drain the JS event queue during recording/capture mode.

        Uses recorder's poll methods which read from JS-side arrays
        (no expose_function callbacks = no greenlet cross-thread issues).
        """
        if not self.is_connected or not self._page:
            return
        recorder = self._recorder
        if recorder is None:
            return
        try:
            recorder.poll_recording()  # Drains __wgt_eventQueue if recording
            recorder.poll_capture()    # Checks __wgt_capture_data if capturing
        except Exception:
            pass  # Page might be navigating

    @Slot()
    def stop_all(self):
        """Stop all active operations."""
        self._poll_timer.stop()
        if self._recorder:
            try:
                self._recorder.stop_recording()
            except Exception:
                pass
        if self._runner:
            try:
                self._runner.stop()
            except Exception:
                pass
        self.disconnect_browser()
