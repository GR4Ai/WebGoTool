"""Workflow Editor — modal dialog for editing a workflow step's parameters.

Uses QStackedWidget to show different forms based on the action type.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QCheckBox,
    QPushButton,
    QDialogButtonBox,
    QStackedWidget,
    QWidget,
    QGroupBox,
    QFileDialog,
)
from PySide6.QtCore import Qt

from flows.schema import WorkflowStep


class WorkflowEditor(QDialog):
    """Dialog for editing a single workflow step."""

    ACTION_TYPES = [
        ("navigate", "🌐 Navigate (open URL)"),
        ("click", "👆 Click (click element)"),
        ("input", "⌨ Input (type text)"),
        ("wait", "⏳ Wait (pause or wait for element)"),
        ("screenshot", "📷 Screenshot (save page image)"),
        ("ocr", "🔍 OCR (recognize text from image)"),
        ("extract", "📋 Extract (get element text/attribute)"),
        ("if", "🔀 If (conditional branch)"),
        ("loop", "🔄 Loop (repeat steps)"),
        ("data_driven", "📊 Data-Driven (batch from Excel)"),
    ]

    CONDITION_TYPES = [
        ("element_exists", "Element exists"),
        ("element_visible", "Element visible"),
        ("text_contains", "Text contains"),
        ("variable_equals", "Variable equals"),
        ("url_contains", "URL contains"),
        ("element_count", "Element count"),
    ]

    LOOP_TYPES = [
        ("for_each", "For each matching element"),
        ("for_range", "For range (start→end)"),
        ("while", "While condition is true"),
    ]

    WAIT_TYPES = [
        ("timeout", "Fixed timeout (ms)"),
        ("selector", "Wait for selector"),
    ]

    def __init__(self, step: WorkflowStep, parent=None):
        super().__init__(parent)
        self.step = step
        self.setWindowTitle(f"Edit Step: {step.id}")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        self._setup_ui()
        self._load_step_data()

    def _setup_ui(self):
        """Build the editor UI."""
        layout = QVBoxLayout(self)

        # ── Action type selector ──
        form = QFormLayout()
        self.cmb_action = QComboBox()
        for value, label in self.ACTION_TYPES:
            self.cmb_action.addItem(label, value)
        self.cmb_action.currentIndexChanged.connect(self._on_action_changed)
        form.addRow("Action:", self.cmb_action)

        self.txt_description = QLineEdit()
        self.txt_description.setPlaceholderText("Optional description...")
        form.addRow("Description:", self.txt_description)

        self.chk_enabled = QCheckBox("Enabled")
        self.chk_enabled.setChecked(True)
        form.addRow("", self.chk_enabled)

        layout.addLayout(form)

        # ── Parameter panels (stacked) ──
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_navigate_panel())
        self.stack.addWidget(self._build_click_panel())
        self.stack.addWidget(self._build_input_panel())
        self.stack.addWidget(self._build_wait_panel())
        self.stack.addWidget(self._build_screenshot_panel())
        self.stack.addWidget(self._build_ocr_panel())
        self.stack.addWidget(self._build_extract_panel())
        self.stack.addWidget(self._build_if_panel())
        self.stack.addWidget(self._build_loop_panel())
        self.stack.addWidget(self._build_data_driven_panel())
        layout.addWidget(self.stack, stretch=1)

        # ── Buttons ──
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    # ═══════════════════════════════════════════════════════════
    # Panel Builders
    # ═══════════════════════════════════════════════════════════

    def _build_navigate_panel(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.nav_url = QLineEdit()
        self.nav_url.setPlaceholderText("https://example.com")
        f.addRow("URL:", self.nav_url)
        self.nav_wait = QComboBox()
        self.nav_wait.addItems(["load", "domcontentloaded", "networkidle"])
        f.addRow("Wait until:", self.nav_wait)
        return w

    def _build_click_panel(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.click_selector = QLineEdit()
        self.click_selector.setPlaceholderText("#login-button or [name='submit']")
        f.addRow("Selector:", self.click_selector)
        self.click_timeout = QSpinBox()
        self.click_timeout.setRange(100, 60000)
        self.click_timeout.setValue(5000)
        f.addRow("Timeout (ms):", self.click_timeout)
        self.click_force = QCheckBox("Force click (skip visibility check)")
        f.addRow("", self.click_force)
        return w

    def _build_input_panel(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.input_selector = QLineEdit()
        self.input_selector.setPlaceholderText("#username")
        f.addRow("Selector:", self.input_selector)
        self.input_value = QLineEdit()
        self.input_value.setPlaceholderText("text to type, or {{variable}}")
        f.addRow("Value:", self.input_value)
        self.input_clear = QCheckBox("Clear before typing")
        self.input_clear.setChecked(True)
        f.addRow("", self.input_clear)
        self.input_delay = QSpinBox()
        self.input_delay.setRange(0, 1000)
        self.input_delay.setValue(0)
        f.addRow("Typing delay (ms):", self.input_delay)
        return w

    def _build_wait_panel(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.wait_type = QComboBox()
        for value, label in self.WAIT_TYPES:
            self.wait_type.addItem(label, value)
        self.wait_type.currentIndexChanged.connect(self._on_wait_type_changed)
        f.addRow("Wait type:", self.wait_type)

        self.wait_timeout = QSpinBox()
        self.wait_timeout.setRange(100, 120000)
        self.wait_timeout.setValue(1000)
        f.addRow("Timeout (ms):", self.wait_timeout)

        self.wait_selector = QLineEdit()
        self.wait_selector.setPlaceholderText(".loading-spinner")
        f.addRow("Selector:", self.wait_selector)
        self.wait_selector.hide()

        self.wait_state = QComboBox()
        self.wait_state.addItems(["visible", "hidden", "attached", "detached"])
        f.addRow("State:", self.wait_state)
        return w

    def _build_screenshot_panel(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.ss_path = QLineEdit()
        self.ss_path.setPlaceholderText("screenshots/result_{{timestamp}}.png")
        f.addRow("File path:", self.ss_path)

        ss_path_layout = QHBoxLayout()
        ss_path_layout.addWidget(self.ss_path)
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self._browse_screenshot_path)
        ss_path_layout.addWidget(btn_browse)

        self.ss_full = QCheckBox("Full page screenshot")
        f.addRow("", self.ss_full)
        self.ss_selector = QLineEdit()
        self.ss_selector.setPlaceholderText("Optional: selector for element only")
        f.addRow("Element selector:", self.ss_selector)
        return w

    def _build_ocr_panel(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.ocr_selector = QLineEdit()
        self.ocr_selector.setPlaceholderText("#captcha-image or img[src*='captcha']")
        f.addRow("Selector (target image):", self.ocr_selector)
        self.ocr_var = QLineEdit("captcha_text")
        f.addRow("Save to variable:", self.ocr_var)
        self.ocr_lang = QComboBox()
        self.ocr_lang.addItems(["en", "ch", "chinese_cht", "japan", "korean"])
        f.addRow("Language:", self.ocr_lang)
        return w

    def _build_extract_panel(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.ext_selector = QLineEdit()
        self.ext_selector.setPlaceholderText(".result-text")
        f.addRow("Selector:", self.ext_selector)
        self.ext_attr = QComboBox()
        self.ext_attr.addItems(["textContent", "innerText", "innerHTML", "value", "href", "src"])
        f.addRow("Attribute:", self.ext_attr)
        self.ext_var = QLineEdit("extracted")
        f.addRow("Save to variable:", self.ext_var)
        return w

    def _build_if_panel(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.if_cond_type = QComboBox()
        for value, label in self.CONDITION_TYPES:
            self.if_cond_type.addItem(label, value)
        f.addRow("Condition:", self.if_cond_type)
        self.if_selector = QLineEdit()
        self.if_selector.setPlaceholderText("#success-message")
        f.addRow("Selector:", self.if_selector)
        self.if_expected = QLineEdit()
        self.if_expected.setPlaceholderText("Expected value / text / URL fragment")
        f.addRow("Expected:", self.if_expected)
        self.if_variable = QLineEdit()
        self.if_variable.setPlaceholderText("Variable name (for variable_equals)")
        f.addRow("Variable:", self.if_variable)
        self.if_timeout = QSpinBox()
        self.if_timeout.setRange(100, 30000)
        self.if_timeout.setValue(3000)
        f.addRow("Timeout (ms):", self.if_timeout)
        return w

    def _build_loop_panel(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.loop_type = QComboBox()
        for value, label in self.LOOP_TYPES:
            self.loop_type.addItem(label, value)
        self.loop_type.currentIndexChanged.connect(self._on_loop_type_changed)
        f.addRow("Loop type:", self.loop_type)

        self.loop_selector = QLineEdit()
        self.loop_selector.setPlaceholderText(".list-item (for for_each)")
        f.addRow("Selector:", self.loop_selector)

        self.loop_var = QLineEdit("loop_index")
        f.addRow("Index variable:", self.loop_var)

        self.loop_start = QSpinBox()
        self.loop_start.setValue(0)
        f.addRow("Start:", self.loop_start)

        self.loop_end = QSpinBox()
        self.loop_end.setValue(10)
        f.addRow("End:", self.loop_end)

        self.loop_step = QSpinBox()
        self.loop_step.setValue(1)
        self.loop_step.setRange(1, 100)
        f.addRow("Step:", self.loop_step)

        self.loop_max = QSpinBox()
        self.loop_max.setRange(1, 10000)
        self.loop_max.setValue(100)
        f.addRow("Max iterations:", self.loop_max)

        self.loop_delay = QSpinBox()
        self.loop_delay.setRange(0, 60000)
        self.loop_delay.setValue(500)
        f.addRow("Delay (ms):", self.loop_delay)
        return w

    def _build_data_driven_panel(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.dd_file = QLineEdit()
        self.dd_file.setPlaceholderText("data/input.xlsx")
        f.addRow("Excel/CSV file:", self.dd_file)

        dd_file_layout = QHBoxLayout()
        dd_file_layout.addWidget(self.dd_file)
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self._browse_data_file)
        dd_file_layout.addWidget(btn_browse)

        self.dd_sheet = QLineEdit("Sheet1")
        f.addRow("Sheet name:", self.dd_sheet)
        self.dd_mapping = QLineEdit()
        self.dd_mapping.setPlaceholderText("username=col_A, password=col_B")
        f.addRow("Column mapping:", self.dd_mapping)
        return w

    # ═══════════════════════════════════════════════════════════
    # Panel switching
    # ═══════════════════════════════════════════════════════════

    def _on_action_changed(self, index: int):
        self.stack.setCurrentIndex(index)

    def _on_wait_type_changed(self, index: int):
        is_selector = self.wait_type.itemData(index) == "selector"
        self.wait_selector.setVisible(is_selector)
        self.wait_state.setVisible(is_selector)

    def _on_loop_type_changed(self, index: int):
        loop_type = self.loop_type.itemData(index)
        is_for_range = loop_type == "for_range"
        self.loop_selector.setVisible(not is_for_range)
        self.loop_start.setVisible(is_for_range)
        self.loop_end.setVisible(is_for_range)
        self.loop_step.setVisible(is_for_range)
        is_while = loop_type == "while"
        self.loop_delay.setVisible(is_while)

    # ═══════════════════════════════════════════════════════════
    # File dialogs
    # ═══════════════════════════════════════════════════════════

    def _browse_screenshot_path(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Screenshot Path", "screenshots/", "PNG (*.png);;All (*)"
        )
        if path:
            self.ss_path.setText(path)

    def _browse_data_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Data File", "",
            "Excel/CSV (*.xlsx *.xls *.csv);;All (*)"
        )
        if path:
            self.dd_file.setText(path)

    # ═══════════════════════════════════════════════════════════
    # Load / Save
    # ═══════════════════════════════════════════════════════════

    def _load_step_data(self):
        """Populate UI fields from the step data."""
        s = self.step
        # Set action combo
        for i in range(self.cmb_action.count()):
            if self.cmb_action.itemData(i) == s.action:
                self.cmb_action.setCurrentIndex(i)
                break

        self.txt_description.setText(s.description)
        self.chk_enabled.setChecked(s.enabled)
        p = s.params

        # Navigate
        if s.action == "navigate":
            self.nav_url.setText(p.get("url", ""))
            wait_idx = self.nav_wait.findText(p.get("waitUntil", "load"))
            if wait_idx >= 0:
                self.nav_wait.setCurrentIndex(wait_idx)

        # Click
        elif s.action == "click":
            self.click_selector.setText(p.get("selector", ""))
            self.click_timeout.setValue(p.get("timeout", 5000))
            self.click_force.setChecked(p.get("force", False))

        # Input
        elif s.action == "input":
            self.input_selector.setText(p.get("selector", ""))
            self.input_value.setText(p.get("value", ""))
            self.input_clear.setChecked(p.get("clear", True))
            self.input_delay.setValue(p.get("delay", 0))

        # Wait
        elif s.action == "wait":
            wt = p.get("type", "timeout")
            for i in range(self.wait_type.count()):
                if self.wait_type.itemData(i) == wt:
                    self.wait_type.setCurrentIndex(i)
                    break
            self.wait_timeout.setValue(p.get("timeout", 1000))
            self.wait_selector.setText(p.get("selector", ""))
            state_idx = self.wait_state.findText(p.get("state", "visible"))
            if state_idx >= 0:
                self.wait_state.setCurrentIndex(state_idx)

        # Screenshot
        elif s.action == "screenshot":
            self.ss_path.setText(p.get("path", ""))
            self.ss_full.setChecked(p.get("fullPage", False))
            self.ss_selector.setText(p.get("selector", ""))

        # OCR
        elif s.action == "ocr":
            self.ocr_selector.setText(p.get("selector", ""))
            self.ocr_var.setText(p.get("variable", "captcha_text"))
            lang_idx = self.ocr_lang.findText(p.get("lang", "en"))
            if lang_idx >= 0:
                self.ocr_lang.setCurrentIndex(lang_idx)

        # Extract
        elif s.action == "extract":
            self.ext_selector.setText(p.get("selector", ""))
            attr_idx = self.ext_attr.findText(p.get("attribute", "textContent"))
            if attr_idx >= 0:
                self.ext_attr.setCurrentIndex(attr_idx)
            self.ext_var.setText(p.get("variable", "extracted"))

        # If
        elif s.action == "if":
            cond = p.get("condition", {})
            for i in range(self.if_cond_type.count()):
                if self.if_cond_type.itemData(i) == cond.get("type", ""):
                    self.if_cond_type.setCurrentIndex(i)
                    break
            self.if_selector.setText(cond.get("selector", ""))
            self.if_expected.setText(cond.get("expected", ""))
            self.if_variable.setText(cond.get("variable", ""))
            self.if_timeout.setValue(cond.get("timeout", 3000))

        # Loop
        elif s.action == "loop":
            lt = p.get("type", "for_each")
            for i in range(self.loop_type.count()):
                if self.loop_type.itemData(i) == lt:
                    self.loop_type.setCurrentIndex(i)
                    break
            self.loop_selector.setText(p.get("selector", ""))
            self.loop_var.setText(p.get("variable", "loop_index"))
            self.loop_start.setValue(p.get("start", 0))
            self.loop_end.setValue(p.get("end", 10))
            self.loop_step.setValue(p.get("step", 1))
            self.loop_max.setValue(p.get("maxIterations", 100))
            self.loop_delay.setValue(p.get("delay", 500))

        # Data driven
        elif s.action == "data_driven":
            self.dd_file.setText(p.get("file", ""))
            self.dd_sheet.setText(p.get("sheet", "Sheet1"))
            mapping = p.get("columnMapping", {})
            self.dd_mapping.setText(", ".join(f"{k}={v}" for k, v in mapping.items()))

    def accept(self):
        """Save UI fields back into the step and validate."""
        self.step.action = self.cmb_action.currentData()
        self.step.description = self.txt_description.text()
        self.step.enabled = self.chk_enabled.isChecked()

        action = self.step.action

        if action == "navigate":
            self.step.params = {
                "url": self.nav_url.text(),
                "waitUntil": self.nav_wait.currentText(),
            }

        elif action == "click":
            self.step.params = {
                "selector": self.click_selector.text(),
                "selectorType": "css",
                "timeout": self.click_timeout.value(),
                "force": self.click_force.isChecked(),
            }

        elif action == "input":
            self.step.params = {
                "selector": self.input_selector.text(),
                "selectorType": "css",
                "value": self.input_value.text(),
                "clear": self.input_clear.isChecked(),
                "delay": self.input_delay.value(),
            }

        elif action == "wait":
            self.step.params = {
                "type": self.wait_type.currentData(),
                "timeout": self.wait_timeout.value(),
                "selector": self.wait_selector.text(),
                "selectorType": "css",
                "state": self.wait_state.currentText(),
            }

        elif action == "screenshot":
            self.step.params = {
                "path": self.ss_path.text(),
                "fullPage": self.ss_full.isChecked(),
                "selector": self.ss_selector.text() or None,
            }

        elif action == "ocr":
            self.step.params = {
                "selector": self.ocr_selector.text(),
                "selectorType": "css",
                "variable": self.ocr_var.text(),
                "lang": self.ocr_lang.currentText(),
            }

        elif action == "extract":
            self.step.params = {
                "selector": self.ext_selector.text(),
                "selectorType": "css",
                "attribute": self.ext_attr.currentText(),
                "variable": self.ext_var.text(),
            }

        elif action == "if":
            self.step.params = {
                "condition": {
                    "type": self.if_cond_type.currentData(),
                    "selector": self.if_selector.text(),
                    "expected": self.if_expected.text(),
                    "variable": self.if_variable.text(),
                    "timeout": self.if_timeout.value(),
                },
                "thenSteps": self.step.params.get("thenSteps", []),
                "elseSteps": self.step.params.get("elseSteps", []),
            }

        elif action == "loop":
            self.step.params = {
                "type": self.loop_type.currentData(),
                "selector": self.loop_selector.text(),
                "selectorType": "css",
                "variable": self.loop_var.text(),
                "start": self.loop_start.value(),
                "end": self.loop_end.value(),
                "step": self.loop_step.value(),
                "maxIterations": self.loop_max.value(),
                "delay": self.loop_delay.value(),
                "bodySteps": self.step.params.get("bodySteps", []),
            }

        elif action == "data_driven":
            mapping = {}
            for part in self.dd_mapping.text().split(","):
                part = part.strip()
                if "=" in part:
                    k, v = part.split("=", 1)
                    mapping[k.strip()] = v.strip()
            self.step.params = {
                "file": self.dd_file.text(),
                "sheet": self.dd_sheet.text(),
                "columnMapping": mapping,
                "steps": self.step.params.get("steps", []),
            }

        # Validate
        if not self.step.action:
            return  # should not happen

        super().accept()
