"""Workflow Runner — executes workflow steps sequentially against a Playwright page."""

from __future__ import annotations

import io
import logging
import os
import re
import time
import uuid
from datetime import datetime
from typing import Any, Callable

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError

from flows.schema import WorkflowModel, WorkflowStep

logger = logging.getLogger(__name__)


class WorkflowRunner:
    """Executes workflow steps sequentially against the connected page.

    Supports: navigate, click, input, wait, screenshot, ocr, extract,
              if, loop, data_driven.
    """

    def __init__(self, page: Page):
        self.page = page
        self.workflow: WorkflowModel | None = None
        self.variables: dict[str, Any] = {}
        self.current_step_index = -1
        self.is_running = False
        self.is_paused = False

        # Callbacks
        self.on_step_start: Callable[[int, WorkflowStep], None] | None = None
        self.on_step_complete: Callable[[int, WorkflowStep, bool, str], None] | None = None
        self.on_log: Callable[[str], None] | None = None
        self.on_error: Callable[[str], None] | None = None
        self.on_done: Callable[[bool], None] | None = None

    # ═══════════════════════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════════════════════

    def load_workflow_dict(self, data: dict[str, Any]):
        """Load a workflow from a dict."""
        self.workflow = WorkflowModel.from_dict(data)
        self.variables = dict(data.get("variables", {}))

    def set_variables(self, vars: dict[str, Any]):
        """Set or override runtime variables."""
        self.variables.update(vars)

    def execute(self):
        """Main execution loop. Iterates through all enabled steps."""
        if not self.workflow:
            self._emit_error("No workflow loaded")
            if self.on_done:
                self.on_done(False)
            return

        self.is_running = True
        self.current_step_index = -1
        steps = self.workflow.steps
        success = True

        i = 0
        while i < len(steps) and self.is_running:
            # Wait if paused
            while self.is_paused and self.is_running:
                time.sleep(0.1)

            if not self.is_running:
                break

            step = steps[i]
            if not step.enabled:
                i += 1
                continue

            self.current_step_index = i
            if self.on_step_start:
                self.on_step_start(i, step)

            ok, msg = self._execute_step(step)

            if self.on_step_complete:
                self.on_step_complete(i, step, ok, msg)

            if not ok:
                self._emit_log(f"Step [{i}] failed: {msg}")
                # Continue by default; could add stop-on-error config
            else:
                self._emit_log(f"Step [{i}] OK: {msg}")

            i += 1

        self.is_running = False
        if self.on_done:
            self.on_done(success)

    def stop(self):
        """Signal the runner to stop at the next step boundary."""
        self.is_running = False
        self.is_paused = False

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    # ═══════════════════════════════════════════════════════════
    # Step Dispatcher
    # ═══════════════════════════════════════════════════════════

    def _execute_step(self, step: WorkflowStep) -> tuple[bool, str]:
        """Dispatch a single step to its handler."""
        handlers = {
            "navigate": self._execute_navigate,
            "click": self._execute_click,
            "input": self._execute_input,
            "wait": self._execute_wait,
            "screenshot": self._execute_screenshot,
            "ocr": self._execute_ocr,
            "extract": self._execute_extract,
            "if": self._execute_if,
            "loop": self._execute_loop,
            "data_driven": self._execute_data_driven,
        }

        handler = handlers.get(step.action)
        if handler is None:
            return False, f"Unknown action: {step.action}"

        try:
            return handler(step)
        except PlaywrightTimeoutError as e:
            return False, f"Timeout: {e}"
        except PlaywrightError as e:
            return False, f"Playwright error: {e}"
        except Exception as e:
            logger.exception("Step execution error")
            return False, f"Error: {e}"

    # ═══════════════════════════════════════════════════════════
    # Step Handlers
    # ═══════════════════════════════════════════════════════════

    def _execute_navigate(self, step: WorkflowStep) -> tuple[bool, str]:
        url = self._resolve_value(step.params.get("url", ""))
        wait_until = step.params.get("waitUntil", "load")
        if not url:
            return False, "No URL specified"
        self.page.goto(url, wait_until=wait_until, timeout=30000)
        return True, f"Navigated to {url}"

    def _execute_click(self, step: WorkflowStep) -> tuple[bool, str]:
        sel = self._get_selector(step)
        timeout = step.params.get("timeout", 5000)
        force = step.params.get("force", False)
        self.page.locator(sel).click(timeout=timeout, force=force)
        return True, f"Clicked {sel}"

    def _execute_input(self, step: WorkflowStep) -> tuple[bool, str]:
        sel = self._get_selector(step)
        value = self._resolve_value(step.params.get("value", ""))
        clear = step.params.get("clear", True)
        delay = step.params.get("delay", 0)

        locator = self.page.locator(sel)
        if clear:
            locator.fill("")
        locator.fill(value)

        return True, f"Input \"{value}\" → {sel}"

    def _execute_wait(self, step: WorkflowStep) -> tuple[bool, str]:
        wait_type = step.params.get("type", "timeout")
        if wait_type == "timeout":
            ms = step.params.get("timeout", 1000)
            self.page.wait_for_timeout(ms)
            return True, f"Waited {ms}ms"
        else:
            sel = self._get_selector(step)
            state = step.params.get("state", "visible")
            timeout = step.params.get("timeout", 10000)
            self.page.wait_for_selector(sel, state=state, timeout=timeout)
            return True, f"Waited for {sel} ({state})"

    def _execute_screenshot(self, step: WorkflowStep) -> tuple[bool, str]:
        path_template = self._resolve_value(
            step.params.get("path", "screenshots/shot_{{timestamp}}.png")
        )
        full_page = step.params.get("fullPage", False)
        sel = step.params.get("selector", None)

        os.makedirs(os.path.dirname(path_template) or "screenshots", exist_ok=True)
        path = self._resolve_variables(path_template)

        if sel:
            self.page.locator(self._get_selector(step)).screenshot(path=path)
        else:
            self.page.screenshot(path=path, full_page=full_page)

        return True, f"Screenshot saved → {path}"

    def _execute_ocr(self, step: WorkflowStep) -> tuple[bool, str]:
        sel = self._get_selector(step)
        var_name = step.params.get("variable", "ocr_text")
        lang = step.params.get("lang", "en")

        # Screenshot the element
        img_bytes = self.page.locator(sel).screenshot()

        # Try PaddleOCR
        try:
            from paddleocr import PaddleOCR
            ocr = PaddleOCR(lang=lang, show_log=False)
            import numpy as np
            from PIL import Image

            img = Image.open(io.BytesIO(img_bytes))
            img_array = np.array(img)
            result = ocr.ocr(img_array)

            text = ""
            if result and result[0]:
                text = " ".join(line[1][0] for line in result[0])

            self.variables[var_name] = text
            return True, f"OCR recognized \"{text[:50]}\" → ${var_name}"

        except ImportError:
            return False, "PaddleOCR not installed (pip install paddleocr)"
        except Exception as e:
            return False, f"OCR error: {e}"

    def _execute_extract(self, step: WorkflowStep) -> tuple[bool, str]:
        sel = self._get_selector(step)
        attr = step.params.get("attribute", "textContent")
        var_name = step.params.get("variable", "extracted")

        locator = self.page.locator(sel)

        if attr == "textContent":
            value = locator.text_content()
        elif attr == "innerText":
            value = locator.inner_text()
        elif attr == "innerHTML":
            value = locator.inner_html()
        elif attr == "value":
            value = locator.input_value()
        else:
            value = locator.get_attribute(attr)

        self.variables[var_name] = value or ""
        return True, f"Extracted \"{str(value)[:50]}\" → ${var_name}"

    def _execute_if(self, step: WorkflowStep) -> tuple[bool, str]:
        condition = step.params.get("condition", {})
        then_steps_raw = step.params.get("thenSteps", [])
        else_steps_raw = step.params.get("elseSteps", [])

        # Convert to WorkflowStep objects if needed
        then_steps = [
            s if isinstance(s, WorkflowStep) else WorkflowStep.from_dict(s)
            for s in then_steps_raw
        ]
        else_steps = [
            s if isinstance(s, WorkflowStep) else WorkflowStep.from_dict(s)
            for s in else_steps_raw
        ]

        result = self._check_condition(condition)

        if result:
            self._emit_log(f"If condition met → executing {len(then_steps)} steps")
            for s in then_steps:
                ok, msg = self._execute_step(s)
                if not ok:
                    return False, f"If/then step failed: {msg}"
            return True, f"If branch executed ({len(then_steps)} steps)"
        else:
            self._emit_log(f"If condition not met → else {len(else_steps)} steps")
            for s in else_steps:
                ok, msg = self._execute_step(s)
                if not ok:
                    return False, f"If/else step failed: {msg}"
            return True, f"Else branch executed ({len(else_steps)} steps)"

    def _execute_loop(self, step: WorkflowStep) -> tuple[bool, str]:
        loop_type = step.params.get("type", "for_each")
        body_steps_raw = step.params.get("bodySteps", [])

        body_steps = [
            s if isinstance(s, WorkflowStep) else WorkflowStep.from_dict(s)
            for s in body_steps_raw
        ]

        if not body_steps:
            return False, "Loop has no body steps"

        max_iter = step.params.get("maxIterations", 100)

        if loop_type == "for_each":
            sel = self._get_selector(step)
            var_name = step.params.get("variable", "loop_index")
            count = self.page.locator(sel).count()
            count = min(count, max_iter)

            for i in range(count):
                if not self.is_running:
                    break
                self.variables[var_name] = i
                # Resolve selectors with current index
                resolved_steps = self._resolve_steps_for_loop(body_steps, i)
                for s in resolved_steps:
                    ok, msg = self._execute_step(s)
                    if not ok:
                        return False, f"Loop iter {i} failed: {msg}"

            return True, f"For-each loop completed ({count} iterations)"

        elif loop_type == "for_range":
            start = step.params.get("start", 0)
            end = step.params.get("end", 10)
            step_val = step.params.get("step", 1)
            var_name = step.params.get("variable", "loop_index")

            for i in range(start, end, step_val):
                if not self.is_running:
                    break
                self.variables[var_name] = i
                for s in body_steps:
                    ok, msg = self._execute_step(s)
                    if not ok:
                        return False, f"Loop iter {i} failed: {msg}"

            return True, f"For-range loop completed ({start}→{end})"

        elif loop_type == "while":
            condition = step.params.get("condition", {})
            delay_ms = step.params.get("delay", 500)
            iteration = 0

            while self.is_running and iteration < max_iter:
                if not self._check_condition(condition):
                    break
                self.variables["loop_index"] = iteration
                for s in body_steps:
                    ok, msg = self._execute_step(s)
                    if not ok:
                        return False, f"While loop iter {iteration} failed: {msg}"
                iteration += 1
                if delay_ms:
                    time.sleep(delay_ms / 1000.0)

            return True, f"While loop completed ({iteration} iterations)"

        return False, f"Unknown loop type: {loop_type}"

    def _execute_data_driven(self, step: WorkflowStep) -> tuple[bool, str]:
        file_path = self._resolve_value(step.params.get("file", ""))
        sheet = step.params.get("sheet", "Sheet1")
        column_mapping = step.params.get("columnMapping", {})
        body_steps_raw = step.params.get("steps", [])

        if not file_path or not os.path.exists(file_path):
            return False, f"File not found: {file_path}"

        try:
            import pandas as pd

            ext = os.path.splitext(file_path)[1].lower()
            if ext == ".csv":
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path, sheet_name=sheet)

            body_steps = [
                s if isinstance(s, WorkflowStep) else WorkflowStep.from_dict(s)
                for s in body_steps_raw
            ]

            for idx, row in df.iterrows():
                if not self.is_running:
                    break
                # Map columns to variables
                for var_name, col_name in column_mapping.items():
                    if col_name in df.columns:
                        self.variables[var_name] = str(row[col_name])
                self.variables["loop_index"] = idx

                for s in body_steps:
                    ok, msg = self._execute_step(s)
                    if not ok:
                        return False, f"Data row {idx} failed: {msg}"

            return True, f"Data-driven completed ({len(df)} rows)"

        except ImportError:
            return False, "pandas not installed (pip install pandas openpyxl)"
        except Exception as e:
            return False, f"Data-driven error: {e}"

    # ═══════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════

    def _get_selector(self, step: WorkflowStep) -> str:
        """Get the resolved selector from step params."""
        sel = step.params.get("selector", "")
        return self._resolve_value(sel)

    def _resolve_value(self, value: str) -> str:
        """Replace {{variable}} placeholders with runtime values.

        Supports: {{variable_name}}, {{timestamp}}, {{random}}, {{uuid}}.
        """
        if not isinstance(value, str):
            return str(value)

        # Replace built-in placeholders
        builtins = {
            "{{timestamp}}": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "{{timestamp_ms}}": str(int(time.time() * 1000)),
            "{{random}}": str(uuid.uuid4())[:8],
            "{{uuid}}": str(uuid.uuid4()),
        }
        for placeholder, replacement in builtins.items():
            value = value.replace(placeholder, replacement)

        # Replace {{variable}} from runtime variables
        def _replacer(match):
            var_name = match.group(1)
            return str(self.variables.get(var_name, match.group(0)))

        return re.sub(r"\{\{(\w+)\}\}", _replacer, value)

    def _resolve_variables(self, text: str) -> str:
        """Alias for _resolve_value."""
        return self._resolve_value(text)

    def _resolve_steps_for_loop(
        self, steps: list[WorkflowStep], index: int
    ) -> list[WorkflowStep]:
        """Deep-copy steps and resolve {{loop_index}} in their params."""
        import copy
        resolved = []
        for s in steps:
            new_s = copy.deepcopy(s)
            new_s.params["selector"] = self._resolve_value(
                new_s.params.get("selector", "")
            )
            new_s.params["value"] = self._resolve_value(
                new_s.params.get("value", "")
            )
            resolved.append(new_s)
        return resolved

    def _check_condition(self, condition: dict) -> bool:
        """Evaluate a condition dict against the current page."""
        cond_type = condition.get("type", "")
        timeout = condition.get("timeout", 3000)

        try:
            if cond_type == "element_exists":
                sel = condition.get("selector", "")
                sel = self._resolve_value(sel)
                return self.page.locator(sel).count() > 0

            elif cond_type == "element_visible":
                sel = condition.get("selector", "")
                sel = self._resolve_value(sel)
                self.page.wait_for_selector(sel, state="visible", timeout=timeout)
                return True

            elif cond_type == "text_contains":
                sel = condition.get("selector", "")
                sel = self._resolve_value(sel)
                expected = condition.get("expected", "")
                expected = self._resolve_value(expected)
                text = self.page.locator(sel).text_content() or ""
                return expected.lower() in text.lower()

            elif cond_type == "variable_equals":
                var_name = condition.get("variable", "")
                expected = condition.get("expected", "")
                actual = str(self.variables.get(var_name, ""))
                return actual == self._resolve_value(expected)

            elif cond_type == "url_contains":
                expected = condition.get("expected", "")
                expected = self._resolve_value(expected)
                return expected.lower() in self.page.url.lower()

            elif cond_type == "element_count":
                sel = condition.get("selector", "")
                sel = self._resolve_value(sel)
                op = condition.get("operator", ">=")
                expected_count = condition.get("count", 1)
                actual_count = self.page.locator(sel).count()
                if op == ">":
                    return actual_count > expected_count
                elif op == "<":
                    return actual_count < expected_count
                elif op == "==":
                    return actual_count == expected_count
                elif op == ">=":
                    return actual_count >= expected_count
                elif op == "<=":
                    return actual_count <= expected_count

            return False

        except PlaywrightTimeoutError:
            return False

    # ═══════════════════════════════════════════════════════════
    # Emitters
    # ═══════════════════════════════════════════════════════════

    def _emit_log(self, message: str):
        if self.on_log:
            self.on_log(message)

    def _emit_error(self, message: str):
        if self.on_error:
            self.on_error(message)
