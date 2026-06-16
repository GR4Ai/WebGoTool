"""BrowserWorker — owns Chrome, Recorder, Runner. Runs in the MAIN thread.

No QThread. Playwright sync API uses greenlets which cannot cross OS threads.
Everything stays in the Qt main thread. QTimer drives polling and step-by-step
playback so the UI never blocks.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot, QTimer
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


class BrowserWorker(QObject):
    """Owns ChromeManager, EventRecorder, WorkflowRunner — all in the main thread."""

    # ── Signals ──
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

        # Polling timer for recording/capture (main thread — SAFE)
        self._poll_timer = QTimer()
        self._poll_timer.setInterval(200)
        self._poll_timer.timeout.connect(self._poll_playwright)

        # Playback step timer (runs one step per tick, UI stays responsive)
        self._playback_timer = QTimer()
        self._playback_timer.setInterval(50)
        self._playback_timer.timeout.connect(self._playback_tick)
        self._playback_steps: list = []
        self._playback_index = -1

    # ═══════════════════════════════════════════════════════════
    # Browser Connection
    # ═══════════════════════════════════════════════════════════

    def connect_browser(self):
        """Launch/connect Chrome."""
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
            self._poll_timer.start()
            self.connected.emit()
            self.log_signal.emit(f"Connected to Chrome — {self._page.url}")
        except Exception as e:
            logger.exception("connect_browser failed")
            self.error_signal.emit(f"Browser connection error: {e}")

    def disconnect_browser(self):
        if self._chrome_manager:
            self._chrome_manager.close()
        self._page = None
        self.is_connected = False
        self._poll_timer.stop()
        self.disconnected.emit()

    def _refresh_page(self):
        if self._chrome_manager:
            new_page = self._chrome_manager.refresh_page()
            if new_page:
                self._page = new_page

    # ═══════════════════════════════════════════════════════════
    # Recording
    # ═══════════════════════════════════════════════════════════

    def start_recording(self):
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

    def stop_recording(self):
        if self._recorder:
            try:
                steps = self._recorder.stop_recording()
                self.log_signal.emit(f"Recording stopped — {len(steps)} steps captured")
            except Exception as e:
                self.log_signal.emit(f"Stop recording error: {e}")
            self._recorder = None

    def _on_recorder_step(self, step):
        self.step_recorded.emit(step.to_dict() if hasattr(step, "to_dict") else step)

    # ═══════════════════════════════════════════════════════════
    # Element Capture
    # ═══════════════════════════════════════════════════════════

    def start_capture_mode(self):
        if not self.is_connected or not self._page:
            self.error_signal.emit("Not connected to Chrome")
            return
        try:
            self._refresh_page()
            from recorder.event_recorder import EventRecorder
            if self._recorder is None:
                self._recorder = EventRecorder(self._page)
                self._recorder.on_log = lambda msg: self.log_signal.emit(msg)
                self._recorder.on_error = lambda msg: self.error_signal.emit(msg)
            self._recorder.on_hover = self._on_capture_hover
            self._recorder.on_capture = self._on_capture_confirm
            self._recorder.on_cancel = self._on_capture_cancel
            self._recorder.inject_capture_overlay()
            self.log_signal.emit("Capture mode ON — click element, Esc to cancel")
        except Exception as e:
            logger.exception("start_capture_mode failed")
            self.error_signal.emit(f"Capture error: {e}")

    def stop_capture_mode(self):
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
    # Playback (QTimer-driven, step-by-step)
    # ═══════════════════════════════════════════════════════════

    def run_workflow(self, workflow_dict: dict):
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
            self._runner.load_workflow_dict(workflow_dict)
            self._runner.on_done = None  # We'll handle completion ourselves

            # Build flat list of steps to execute (expand nested if/loop)
            self._playback_steps = list(self._runner.workflow.steps)
            self._playback_index = -1
            self._run_next_step()
        except Exception as e:
            logger.exception("run_workflow failed")
            self.error_signal.emit(f"Playback error: {e}")
            self.playback_finished.emit(False)

    def _run_next_step(self):
        """Advance to next step and execute it, then schedule next via timer."""
        self._playback_index += 1
        if self._playback_index >= len(self._playback_steps):
            # All done
            self.log_signal.emit("▶ Playback complete")
            self.playback_finished.emit(True)
            return
        step = self._playback_steps[self._playback_index]
        if not step.enabled:
            self._run_next_step()
            return
        # Execute one step
        ok, msg = self._runner._execute_step(step)
        # Report
        self.playback_step_start.emit(self._playback_index, step.to_dict())
        self.playback_step_done.emit(self._playback_index, ok, msg)
        # Schedule next step (allows UI to breathe)
        QTimer.singleShot(50, self._run_next_step)

    def _playback_tick(self):
        """No longer used (replaced by _run_next_step chaining)."""
        pass

    def stop_workflow(self):
        self._playback_steps = []
        self._playback_index = -1

    def _on_playback_step_start(self, index: int, step):
        pass  # Handled inline

    def _on_playback_step_complete(self, index: int, step, success: bool, message: str):
        pass  # Handled inline

    # ═══════════════════════════════════════════════════════════
    # Polling (main thread — SAFE)
    # ═══════════════════════════════════════════════════════════

    def _poll_playwright(self):
        """Drain JS event queue during recording/capture mode."""
        if not self.is_connected or not self._page:
            return
        recorder = self._recorder
        if recorder is None:
            return
        try:
            recorder.poll_recording()
            recorder.poll_capture()
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    # Lifecycle
    # ═══════════════════════════════════════════════════════════

    def stop_all(self):
        self._poll_timer.stop()
        self._playback_timer.stop()
        if self._recorder:
            try:
                self._recorder.stop_recording()
            except Exception:
                pass
        self.disconnect_browser()
