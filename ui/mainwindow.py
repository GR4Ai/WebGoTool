"""Main application window — toolbar, step list, log panel, and thread bridge."""

import json
import logging
import os
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow,
    QToolBar,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QStatusBar,
    QFileDialog,
    QMessageBox,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QAbstractItemView,
    QSplitter,
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtGui import QAction, QKeySequence, QColor, QTextCharFormat, QTextCursor, QFont

from flows.schema import WorkflowModel, WorkflowStep
from browser.browser_worker import BrowserWorker
from utils.logger import get_qt_handler

logger = logging.getLogger(__name__)


class StepListWidget(QListWidget):
    """Custom list widget for workflow steps with drag-drop support."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)


class MainWindow(QMainWindow):
    """Central UI hub for WebGoTool."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("WebGoTool — Web Automation Tool")
        self.resize(900, 650)
        self.setMinimumSize(700, 450)

        # State
        self.workflow = WorkflowModel(name="New Workflow")
        self.browser_worker: BrowserWorker | None = None
        self.is_recording = False
        self.is_playing = False
        self.capture_mode = False

        self._setup_ui()
        self._setup_shortcuts()
        self._setup_worker()

        logger.info("MainWindow initialized")

    # ═══════════════════════════════════════════════════════════
    # UI Setup
    # ═══════════════════════════════════════════════════════════

    def _setup_ui(self):
        """Build the main window layout."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(4)

        # ── Toolbar ──
        self._setup_toolbar()

        # ── Workflow name ──
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Workflow:"))
        self.input_workflow_name = QLineEdit("New Workflow")
        self.input_workflow_name.textChanged.connect(self._on_name_changed)
        name_layout.addWidget(self.input_workflow_name, stretch=1)
        main_layout.addLayout(name_layout)

        # ── Step list + log panel (splitter) ──
        splitter = QSplitter(Qt.Vertical)

        self.step_list = StepListWidget()
        self.step_list.customContextMenuRequested.connect(self._show_step_context_menu)
        self.step_list.itemDoubleClicked.connect(self._on_step_double_clicked)
        splitter.addWidget(self.step_list)

        self.log_panel = QPlainTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setMaximumBlockCount(1000)
        self.log_panel.setFont(QFont("Consolas", 9))
        splitter.addWidget(self.log_panel)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter, stretch=1)

        # ── Status bar ──
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("Not connected")
        self.status_bar.addPermanentWidget(self.status_label)

        # ── Wire Qt log handler ──
        qt_handler = get_qt_handler()
        if qt_handler:
            qt_handler.set_callback(self._log_signal_receiver)

    def _setup_toolbar(self):
        """Create the action toolbar."""
        self.toolbar = QToolBar("Actions")
        self.toolbar.setMovable(False)
        self.toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(self.toolbar)

        # Record button
        self.btn_record = QPushButton("⏺ Record")
        self.btn_record.setCheckable(True)
        self.btn_record.clicked.connect(self.on_record_clicked)
        self.toolbar.addWidget(self.btn_record)

        # Stop button
        self.btn_stop = QPushButton("⏹ Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.on_stop_clicked)
        self.toolbar.addWidget(self.btn_stop)

        self.toolbar.addSeparator()

        # Run button
        self.btn_run = QPushButton("▶ Run")
        self.btn_run.clicked.connect(self.on_run_clicked)
        self.toolbar.addWidget(self.btn_run)

        self.toolbar.addSeparator()

        # Capture button
        self.btn_capture = QPushButton("🎯 Capture")
        self.btn_capture.setCheckable(True)
        self.btn_capture.clicked.connect(self.on_capture_clicked)
        self.toolbar.addWidget(self.btn_capture)

        self.toolbar.addSeparator()

        # Save button
        self.btn_save = QPushButton("💾 Save")
        self.btn_save.clicked.connect(self.on_save_clicked)
        self.toolbar.addWidget(self.btn_save)

        # Load button
        self.btn_load = QPushButton("📂 Load")
        self.btn_load.clicked.connect(self.on_load_clicked)
        self.toolbar.addWidget(self.btn_load)

        self.toolbar.addSeparator()

        # Connect button
        self.btn_connect = QPushButton("🔗 Connect")
        self.btn_connect.clicked.connect(self.on_connect_clicked)
        self.toolbar.addWidget(self.btn_connect)

    def _setup_shortcuts(self):
        """Register keyboard shortcuts."""
        QAction("Save", self, shortcut=QKeySequence("Ctrl+S"),
                triggered=self.on_save_clicked)
        QAction("Run", self, shortcut=QKeySequence("F5"),
                triggered=self.on_run_clicked)
        QAction("Record", self, shortcut=QKeySequence("Ctrl+R"),
                triggered=self.on_record_clicked)
        QAction("Stop", self, shortcut=QKeySequence("Escape"),
                triggered=self.on_stop_clicked)
        QAction("Load", self, shortcut=QKeySequence("Ctrl+O"),
                triggered=self.on_load_clicked)

    # ═══════════════════════════════════════════════════════════
    # Worker Thread
    # ═══════════════════════════════════════════════════════════

    def _setup_worker(self):
        """Create BrowserWorker (runs in main thread — no QThread)."""
        self.browser_worker = BrowserWorker()

        # Connect worker signals → UI slots
        self.browser_worker.log_signal.connect(self._on_log)
        self.browser_worker.error_signal.connect(self._on_error)
        self.browser_worker.connected.connect(self._on_browser_connected)
        self.browser_worker.disconnected.connect(self._on_browser_disconnected)
        self.browser_worker.step_recorded.connect(self._on_step_recorded)
        self.browser_worker.element_hovered.connect(self._on_element_hovered)
        self.browser_worker.element_captured.connect(self._on_element_captured)
        self.browser_worker.capture_cancelled.connect(self._on_capture_cancelled)
        self.browser_worker.playback_step_start.connect(self._on_playback_step_start)
        self.browser_worker.playback_step_done.connect(self._on_playback_step_done)
        self.browser_worker.playback_finished.connect(self._on_playback_done)

        logger.info("BrowserWorker initialized (main thread)")

    def closeEvent(self, event):
        """Clean up when window closes."""
        if self.browser_worker:
            self.browser_worker.stop_all()
        event.accept()

    # ═══════════════════════════════════════════════════════════
    # Toolbar Actions
    # ═══════════════════════════════════════════════════════════

    def on_connect_clicked(self):
        """Connect to Chrome browser."""
        self.status_label.setText("Connecting...")
        self.append_log("Connecting to Chrome...")
        if self.browser_worker:
            self.browser_worker.connect_browser()

    def on_record_clicked(self):
        """Toggle recording mode."""
        if not self.browser_worker or not self.browser_worker.is_connected:
            self.append_log("⚠ Please connect to Chrome first", "WARN")
            self.btn_record.setChecked(False)
            return

        if self.btn_record.isChecked():
            self.is_recording = True
            self.btn_stop.setEnabled(True)
            self.btn_run.setEnabled(False)
            self.btn_capture.setEnabled(False)
            self.status_label.setText("Recording...")
            self.append_log("● Recording started")
            self.browser_worker.start_recording)
        else:
            self._stop_recording()

    def on_stop_clicked(self):
        """Stop recording or playback."""
        if self.is_recording:
            self._stop_recording()
        if self.is_playing:
            self._stop_playback()
        if self.capture_mode:
            self.on_capture_clicked()

    def on_run_clicked(self):
        """Execute the workflow."""
        if not self.browser_worker or not self.browser_worker.is_connected:
            self.append_log("⚠ Please connect to Chrome first", "WARN")
            return

        if not self.workflow.steps:
            QMessageBox.information(self, "No Steps", "The workflow has no steps to execute.")
            return

        self._build_workflow_from_list()

        self.is_playing = True
        self.btn_run.setEnabled(False)
        self.btn_record.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_label.setText("Running...")
        self.append_log("▶ Running workflow...")

        self.browser_worker.run_workflow(self.workflow.to_dict())

    def on_capture_clicked(self):
        """Toggle element capture mode."""
        if not self.browser_worker or not self.browser_worker.is_connected:
            self.append_log("⚠ Please connect to Chrome first", "WARN")
            self.btn_capture.setChecked(False)
            return

        if self.btn_capture.isChecked():
            self.capture_mode = True
            self.status_label.setText("Capture mode — click an element in Chrome")
            self.append_log("🎯 Capture mode ON — click element in Chrome, press Esc to cancel")
            self.browser_worker.start_capture_mode)
        else:
            self.capture_mode = False
            self.status_label.setText("Connected")
            self.browser_worker.stop_capture_mode)

    def on_save_clicked(self):
        """Save workflow to file."""
        self._build_workflow_from_list()
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save Workflow", "workflow.json",
            "JSON Files (*.json);;All Files (*)"
        )
        if filepath:
            try:
                self.workflow.save(filepath)
                self.append_log(f"✓ Workflow saved to {filepath}", "SUCCESS")
                self.status_label.setText(f"Saved: {os.path.basename(filepath)}")
            except Exception as e:
                self.append_log(f"✗ Save failed: {e}", "ERROR")

    def on_load_clicked(self):
        """Load workflow from file."""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Load Workflow", "", "JSON Files (*.json);;All Files (*)"
        )
        if filepath and os.path.exists(filepath):
            try:
                self.workflow = WorkflowModel.load(filepath)
                self.input_workflow_name.setText(self.workflow.name)
                self._refresh_step_list()
                self.append_log(f"✓ Loaded workflow: {self.workflow.name} "
                               f"({len(self.workflow.steps)} steps)", "SUCCESS")
                self.status_label.setText(f"Loaded: {os.path.basename(filepath)}")
            except Exception as e:
                self.append_log(f"✗ Load failed: {e}", "ERROR")

    # ═══════════════════════════════════════════════════════════
    # Step List Management
    # ═══════════════════════════════════════════════════════════

    def add_step(self, step: WorkflowStep):
        """Add a step to both the model and the list widget."""
        self.workflow.add_step(step)
        self._add_step_widget(step)

    def _add_step_widget(self, step: WorkflowStep):
        """Add a step to the list widget (no model change)."""
        text = self._format_step_text(step)
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, step.to_dict())
        item.setFlags(item.flags() | Qt.ItemIsDragEnabled)
        if not step.enabled:
            item.setForeground(QColor("gray"))
        self.step_list.addItem(item)

    def remove_step(self, index: int):
        """Remove step at index."""
        if 0 <= index < self.step_list.count():
            self.step_list.takeItem(index)
            self.workflow.remove_step(index)

    def clear_steps(self):
        """Clear all steps from list and model."""
        self.step_list.clear()
        self.workflow.steps.clear()

    def _refresh_step_list(self):
        """Rebuild the step list from the workflow model."""
        self.step_list.clear()
        for step in self.workflow.steps:
            self._add_step_widget(step)

    def _format_step_text(self, step: WorkflowStep) -> str:
        """Format a step for display in the list."""
        action_icons = {
            "navigate": "🌐",
            "click": "👆",
            "input": "⌨",
            "wait": "⏳",
            "screenshot": "📷",
            "ocr": "🔍",
            "extract": "📋",
            "if": "🔀",
            "loop": "🔄",
            "data_driven": "📊",
        }
        icon = action_icons.get(step.action, "❓")
        desc = step.description or self._summarize_params(step)
        enabled = "" if step.enabled else " [DISABLED]"
        return f"[{step.id}] {icon} {step.action.upper()}: {desc}{enabled}"

    def _summarize_params(self, step: WorkflowStep) -> str:
        """Generate a brief description from step params."""
        p = step.params
        if step.action == "navigate":
            return p.get("url", "")
        if step.action == "input":
            sel = p.get("selector", "")
            val = p.get("value", "")
            return f"{sel} ← \"{val}\""
        if step.action == "click":
            return p.get("selector", "")
        if step.action == "wait":
            if p.get("type") == "timeout":
                return f"{p.get('timeout', 1000)}ms"
            return p.get("selector", "")
        if step.action == "if":
            cond = p.get("condition", {})
            return cond.get("type", "?")
        if step.action == "loop":
            return f"{p.get('type', '?')} ({p.get('maxIterations', '?')} max)"
        return ""

    def _build_workflow_from_list(self):
        """Sync step list content back into the workflow model."""
        self.workflow.steps.clear()
        for i in range(self.step_list.count()):
            item = self.step_list.item(i)
            step_dict = item.data(Qt.UserRole)
            if step_dict:
                self.workflow.steps.append(WorkflowStep.from_dict(step_dict))

    # ═══════════════════════════════════════════════════════════
    # Context Menu
    # ═══════════════════════════════════════════════════════════

    def _show_step_context_menu(self, pos):
        """Right-click context menu for steps."""
        item = self.step_list.itemAt(pos)
        if not item:
            return

        menu = QMenu(self)
        edit_action = menu.addAction("✏ Edit")
        menu.addSeparator()
        disable_action = menu.addAction("✓ Toggle Enabled")
        menu.addSeparator()
        up_action = menu.addAction("↑ Move Up")
        down_action = menu.addAction("↓ Move Down")
        menu.addSeparator()
        del_action = menu.addAction("🗑 Delete")
        menu.addSeparator()
        dup_action = menu.addAction("📋 Duplicate")

        action = menu.exec(self.step_list.viewport().mapToGlobal(pos))

        index = self.step_list.row(item)
        if action == edit_action:
            self._open_step_editor(index)
        elif action == disable_action:
            self._toggle_step_enabled(index)
        elif action == up_action and index > 0:
            self._move_step_up(index)
        elif action == down_action and index < self.step_list.count() - 1:
            self._move_step_down(index)
        elif action == del_action:
            self.remove_step(index)
        elif action == dup_action:
            step_dict = item.data(Qt.UserRole)
            if step_dict:
                new_step = WorkflowStep.from_dict(step_dict)
                new_step.id = str(hash(datetime.now().isoformat()))[:8]
                self.workflow.steps.insert(index + 1, new_step)
                self._refresh_step_list()

    def _on_step_double_clicked(self, item: QListWidgetItem):
        """Open editor on double-click."""
        index = self.step_list.row(item)
        self._open_step_editor(index)

    def _open_step_editor(self, index: int):
        """Open the workflow editor dialog for a step."""
        from ui.workflow_editor import WorkflowEditor
        if 0 <= index < len(self.workflow.steps):
            step = self.workflow.steps[index]
            dialog = WorkflowEditor(step, self)
            if dialog.exec():
                # Update step in model and refresh list
                self.workflow.steps[index] = dialog.step
                self._refresh_step_list()

    def _toggle_step_enabled(self, index: int):
        """Toggle step enabled state."""
        if 0 <= index < len(self.workflow.steps):
            self.workflow.steps[index].enabled = not self.workflow.steps[index].enabled
            self._refresh_step_list()

    def _move_step_up(self, index: int):
        self.workflow.move_step(index, index - 1)
        self._refresh_step_list()

    def _move_step_down(self, index: int):
        self.workflow.move_step(index, index + 1)
        self._refresh_step_list()

    # ═══════════════════════════════════════════════════════════
    # Logging
    # ═══════════════════════════════════════════════════════════

    def append_log(self, message: str, level: str = "INFO"):
        """Append a message to the log panel with color."""
        colors = {
            "INFO": QColor("black"),
            "WARN": QColor("darkorange"),
            "ERROR": QColor("red"),
            "SUCCESS": QColor("darkgreen"),
            "DEBUG": QColor("gray"),
        }
        color = colors.get(level, QColor("black"))
        fmt = QTextCharFormat()
        fmt.setForeground(color)

        cursor = self.log_panel.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(
            f"[{datetime.now().strftime('%H:%M:%S')}] {message}\n", fmt
        )
        self.log_panel.setTextCursor(cursor)
        self.log_panel.ensureCursorVisible()

    @Slot(str)
    def _log_signal_receiver(self, message: str):
        """Receive log messages from QtLogHandler."""
        self.append_log(message, "DEBUG")

    # ═══════════════════════════════════════════════════════════
    # Internal Helpers
    # ═══════════════════════════════════════════════════════════

    def _stop_recording(self):
        """Stop the recorder."""
        self.is_recording = False
        self.btn_record.setChecked(False)
        self.btn_record.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_run.setEnabled(True)
        self.btn_capture.setEnabled(True)
        self.status_label.setText("Connected")
        self.append_log("■ Recording stopped")
        if self.browser_worker:
            self.browser_worker.stop_recording)

    def _stop_playback(self):
        """Stop the playback engine."""
        self.is_playing = False
        self.btn_run.setEnabled(True)
        self.btn_record.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_label.setText("Connected")
        self.append_log("■ Playback stopped")
        if self.browser_worker:
            self.browser_worker.stop_workflow)

    def _on_name_changed(self, text: str):
        self.workflow.name = text

    # ═══════════════════════════════════════════════════════════
    # Worker Signal Slots
    # ═══════════════════════════════════════════════════════════

    @Slot(str)
    def _on_log(self, message: str):
        self.append_log(message)

    @Slot(str)
    def _on_error(self, error_message: str):
        self.append_log(f"✗ {error_message}", "ERROR")
        QMessageBox.warning(self, "Error", error_message)

    @Slot()
    def _on_browser_connected(self):
        self.status_label.setText("Connected ✓")
        self.append_log("✓ Connected to Chrome", "SUCCESS")
        self.btn_connect.setEnabled(False)
        self.btn_capture.setEnabled(True)
        self.btn_record.setEnabled(True)

    @Slot()
    def _on_browser_disconnected(self):
        self.status_label.setText("Disconnected")
        self.append_log("Disconnected from Chrome", "WARN")
        self.btn_connect.setEnabled(True)
        self.btn_capture.setEnabled(False)
        self.btn_record.setEnabled(False)
        self.btn_run.setEnabled(False)

    @Slot(dict)
    def _on_step_recorded(self, step_dict: dict):
        step = WorkflowStep.from_dict(step_dict)
        self.add_step(step)
        self.append_log(f"● Recorded: {self._format_step_text(step)}")

    @Slot(dict)
    def _on_element_hovered(self, element_info: dict):
        tag = element_info.get("tag", "?")
        sel = element_info.get("cssSelector", "") or element_info.get("xpath", "")
        self.status_label.setText(f"Hover: <{tag}> {sel[:60]}")

    @Slot(dict)
    def _on_element_captured(self, element_info: dict):
        from ui.workflow_editor import WorkflowEditor

        # Guess action from element type
        tag = element_info.get("tag", "")
        el_type = element_info.get("type", "")
        if tag == "input" and el_type in ("text", "password", "email", "number", "search", ""):
            action = "input"
        elif tag in ("select", "textarea"):
            action = "input"
        elif tag in ("a", "button") or el_type in ("submit", "button"):
            action = "click"
        elif tag in ("img",):
            action = "ocr"
        else:
            action = "click"

        # Determine best selector
        sel = ""
        if element_info.get("id"):
            sel = f"#{element_info['id']}"
        elif element_info.get("name"):
            sel = f"[name=\"{element_info['name']}\"]"
        else:
            sel = element_info.get("cssSelector", "") or element_info.get("xpath", "")

        step = WorkflowStep(
            action=action,
            params={
                "selector": sel,
                "selectorType": "css",
                "value": element_info.get("value", ""),
            },
            description=element_info.get("text", "") or f"{tag}#{element_info.get('id', '')}",
        )

        # Open editor so user can confirm/customize
        dialog = WorkflowEditor(step, self)
        if dialog.exec():
            self.add_step(dialog.step)
            self.append_log(f"🎯 Captured: {self._format_step_text(dialog.step)}", "SUCCESS")

        self.btn_capture.setChecked(False)
        if self.browser_worker:
            self.browser_worker.stop_capture_mode)
        self.capture_mode = False
        self.status_label.setText("Connected ✓")

    @Slot()
    def _on_capture_cancelled(self):
        self.capture_mode = False
        self.btn_capture.setChecked(False)
        self.status_label.setText("Connected ✓")
        self.append_log("Capture cancelled")

    @Slot(int, dict)
    def _on_playback_step_start(self, step_index: int, step_dict: dict):
        step = WorkflowStep.from_dict(step_dict)
        self.append_log(f"▶ [{step_index}] {self._format_step_text(step)}")
        # Highlight current step in list
        if step_index < self.step_list.count():
            self.step_list.setCurrentRow(step_index)

    @Slot(int, bool, str)
    def _on_playback_step_done(self, step_index: int, success: bool, message: str):
        level = "SUCCESS" if success else "ERROR"
        self.append_log(f"  {'✓' if success else '✗'} {message}", level)

    @Slot(bool)
    def _on_playback_done(self, success: bool):
        self.is_playing = False
        self.btn_run.setEnabled(True)
        self.btn_record.setEnabled(True)
        self.btn_stop.setEnabled(False)
        status = "Done ✓" if success else "Failed ✗"
        self.status_label.setText(status)
        self.append_log(f"▶ Playback {status}", "SUCCESS" if success else "ERROR")
