"""Event Recorder — injects JS into the page to capture user interactions.

Uses page.expose_function() for JS→Python callbacks.
Supports: click recording, input recording, element capture overlay.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from playwright.sync_api import Page

from flows.schema import WorkflowStep

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# JavaScript: Recorder injection
# ═══════════════════════════════════════════════════════════════

RECORDER_JS = r"""
(function() {
    if (window.__webGoToolRecorderInstalled) return;
    window.__webGoToolRecorderInstalled = true;

    function buildCssSelector(el) {
        if (!el || el.nodeType !== 1) return '';
        if (el.id) return '#' + CSS.escape(el.id);
        const parts = [];
        let current = el;
        while (current && current.nodeType === 1 && current !== document.body) {
            let sel = current.tagName.toLowerCase();
            if (current.id) { parts.unshift('#' + CSS.escape(current.id)); break; }
            if (current.className && typeof current.className === 'string') {
                const classes = current.className.trim().split(/\s+/).filter(Boolean);
                if (classes.length) sel += '.' + classes.map(c => CSS.escape(c)).join('.');
            }
            const parent = current.parentElement;
            if (parent) {
                const siblings = Array.from(parent.children).filter(s => s.tagName === current.tagName);
                if (siblings.length > 1) sel += ':nth-child(' + (siblings.indexOf(current)+1) + ')';
            }
            parts.unshift(sel);
            try {
                if (document.querySelectorAll(parts.join(' > ')).length === 1) break;
            } catch(e) {}
            current = current.parentElement;
        }
        return parts.join(' > ') || '*';
    }

    function buildXPath(el) {
        if (!el || el.nodeType !== 1) return '';
        if (el.id) return '//*[@id="' + el.id + '"]';
        const parts = [];
        let current = el;
        while (current && current.nodeType === 1 && current !== document.documentElement) {
            let tag = current.tagName.toLowerCase();
            if (current.id) { parts.unshift('//*[@id="' + current.id + '"]'); break; }
            const parent = current.parentElement;
            if (parent) {
                const siblings = Array.from(parent.children).filter(s => s.tagName === current.tagName);
                if (siblings.length > 1) tag += '[' + (siblings.indexOf(current) + 1) + ']';
            }
            parts.unshift(tag);
            current = current.parentElement;
        }
        return '/' + parts.join('/');
    }

    function getElementInfo(el) {
        if (!el) return null;
        const info = {
            tag: el.tagName ? el.tagName.toLowerCase() : '',
            id: el.id || '',
            name: el.getAttribute('name') || '',
            className: (typeof el.className === 'string') ? el.className : '',
            type: el.type || '',
            text: (el.textContent || '').substring(0, 150).trim(),
            href: el.href || '',
            cssSelector: buildCssSelector(el),
            xpath: buildXPath(el),
            attributes: {}
        };
        ['id','name','class','type','placeholder','aria-label','data-testid','title','value'].forEach(function(a) {
            const v = el.getAttribute(a);
            if (v) info.attributes[a] = v;
        });
        return info;
    }

    // --- Click Recording ---
    document.addEventListener('click', function(e) {
        if (!window.__webGoToolRecorderActive) return;
        const info = getElementInfo(e.target);
        if (!info) return;
        info.timestamp = Date.now();
        info.event = 'click';
        window.__webGoTool_onEvent(JSON.stringify(info));
    }, true);

    // --- Input Recording ---
    document.addEventListener('input', function(e) {
        if (!window.__webGoToolRecorderActive) return;
        const el = e.target;
        if (!el || !el.matches('input,textarea,[contenteditable="true"]')) return;
        const info = getElementInfo(el);
        if (!info) return;
        info.value = el.value || el.textContent || '';
        info.timestamp = Date.now();
        info.event = 'input';
        // Debounce: mark the last input event per element
        if (el.__wgt_lastEvent) clearTimeout(el.__wgt_lastEvent);
        el.__wgt_lastEvent = setTimeout(function() {
            window.__webGoTool_onEvent(JSON.stringify(info));
            el.__wgt_lastEvent = null;
        }, 300);
    }, true);

    // --- Change Recording (select, checkbox, radio) ---
    document.addEventListener('change', function(e) {
        if (!window.__webGoToolRecorderActive) return;
        const el = e.target;
        if (!el || !el.matches('select,input[type="checkbox"],input[type="radio"]')) return;
        const info = getElementInfo(el);
        if (!info) return;
        info.value = el.value || (el.checked ? 'checked' : 'unchecked');
        info.timestamp = Date.now();
        info.event = 'change';
        window.__webGoTool_onEvent(JSON.stringify(info));
    }, true);
})();
"""

# ═══════════════════════════════════════════════════════════════
# JavaScript: Element capture overlay
# ═══════════════════════════════════════════════════════════════

CAPTURE_OVERLAY_JS = r"""
(function() {
    // Remove stale overlay
    const old = document.getElementById('__wgt_overlay');
    if (old) old.remove();

    window.__wgt_capture_active = true;

    const overlay = document.createElement('div');
    overlay.id = '__wgt_overlay';
    overlay.style.cssText =
        'position:fixed;top:0;left:0;width:100vw;height:100vh;' +
        'z-index:2147483647;cursor:crosshair;background:rgba(0,0,0,0.05);';
    let lastEl = null;

    function buildCssSelector(el) {
        if (!el || el.nodeType !== 1) return '';
        if (el.id) return '#' + CSS.escape(el.id);
        const parts = [];
        let current = el;
        while (current && current.nodeType === 1 && current !== document.body) {
            let sel = current.tagName.toLowerCase();
            if (current.id) { parts.unshift('#' + CSS.escape(current.id)); break; }
            if (current.className && typeof current.className === 'string') {
                const classes = current.className.trim().split(/\s+/).filter(Boolean);
                if (classes.length) sel += '.' + classes.map(c => CSS.escape(c)).join('.');
            }
            const parent = current.parentElement;
            if (parent) {
                const siblings = Array.from(parent.children).filter(s => s.tagName === current.tagName);
                if (siblings.length > 1) sel += ':nth-child(' + (siblings.indexOf(current)+1) + ')';
            }
            parts.unshift(sel);
            try {
                if (document.querySelectorAll(parts.join(' > ')).length === 1) break;
            } catch(e) {}
            current = current.parentElement;
        }
        return parts.join(' > ') || '*';
    }

    function buildXPath(el) {
        if (!el || el.nodeType !== 1) return '';
        if (el.id) return '//*[@id="' + el.id + '"]';
        const parts = [];
        let current = el;
        while (current && current.nodeType === 1 && current !== document.documentElement) {
            let tag = current.tagName.toLowerCase();
            if (current.id) { parts.unshift('//*[@id="' + current.id + '"]'); break; }
            const parent = current.parentElement;
            if (parent) {
                const siblings = Array.from(parent.children).filter(s => s.tagName === current.tagName);
                if (siblings.length > 1) tag += '[' + (siblings.indexOf(current) + 1) + ']';
            }
            parts.unshift(tag);
            current = current.parentElement;
        }
        return '/' + parts.join('/');
    }

    overlay.addEventListener('mousemove', function(e) {
        if (!window.__wgt_capture_active) return;
        overlay.style.pointerEvents = 'none';
        const el = document.elementFromPoint(e.clientX, e.clientY);
        overlay.style.pointerEvents = 'auto';
        if (el && el !== lastEl && el !== overlay) {
            if (lastEl) { lastEl.style.outline = lastEl.__wgt_outline || ''; }
            el.__wgt_outline = el.style.outline;
            el.style.outline = '2px solid #FF4444';
            lastEl = el;
            const info = {
                tag: el.tagName ? el.tagName.toLowerCase() : '',
                id: el.id || '',
                className: (typeof el.className === 'string') ? el.className : '',
                name: el.getAttribute('name') || '',
                type: el.type || '',
                text: (el.textContent || '').substring(0, 100).trim(),
                cssSelector: el.id ? '#'+CSS.escape(el.id) : buildCssSelector(el),
                xpath: el.id ? '//*[@id="'+el.id+'"]' : buildXPath(el),
                attributes: {}
            };
            ['id','name','class','type','placeholder','aria-label','data-testid','title'].forEach(function(a) {
                const v = el.getAttribute(a);
                if (v) info.attributes[a] = v;
            });
            window.__webGoTool_onHover(JSON.stringify(info));
        }
    });

    overlay.addEventListener('click', function(e) {
        if (!window.__wgt_capture_active) return;
        e.preventDefault();
        e.stopPropagation();
        overlay.style.pointerEvents = 'none';
        const el = document.elementFromPoint(e.clientX, e.clientY);
        if (el && el !== overlay) {
            const info = {
                tag: el.tagName ? el.tagName.toLowerCase() : '',
                id: el.id || '',
                name: el.getAttribute('name') || '',
                className: (typeof el.className === 'string') ? el.className : '',
                type: el.type || '',
                text: (el.textContent || '').substring(0, 150).trim(),
                href: el.href || '',
                cssSelector: el.id ? '#'+CSS.escape(el.id) : buildCssSelector(el),
                xpath: el.id ? '//*[@id="'+el.id+'"]' : buildXPath(el),
                value: el.value || '',
                attributes: {}
            };
            ['id','name','class','type','placeholder','aria-label','data-testid','title'].forEach(function(a) {
                const v = el.getAttribute(a);
                if (v) info.attributes[a] = v;
            });
            window.__webGoTool_onCapture(JSON.stringify(info));
        }
        cleanup();
    }, true);

    function cleanup() {
        window.__wgt_capture_active = false;
        if (lastEl) { lastEl.style.outline = lastEl.__wgt_outline || ''; lastEl = null; }
        if (overlay.parentNode) overlay.remove();
    }

    document.addEventListener('keydown', function handler(e) {
        if (e.key === 'Escape') {
            window.__webGoTool_onCancel();
            cleanup();
            document.removeEventListener('keydown', handler);
        }
    });

    document.body.appendChild(overlay);
})();
"""

# ═══════════════════════════════════════════════════════════════
# Cleanup script
# ═══════════════════════════════════════════════════════════════

CLEANUP_JS = """
(function() {
    window.__webGoToolRecorderActive = false;
    window.__webGoToolRecorderInstalled = false;
    const overlay = document.getElementById('__wgt_overlay');
    if (overlay) overlay.remove();
    // Clean up outlines
    const all = document.querySelectorAll('*');
    for (let el of all) {
        if (el.__wgt_outline !== undefined) {
            el.style.outline = el.__wgt_outline;
            delete el.__wgt_outline;
        }
    }
})();
"""


class EventRecorder:
    """Injects JS into the page and receives interaction callbacks."""

    def __init__(self, page: Page):
        self.page = page
        self.is_recording = False
        self._capture_active = False
        self.recorded_steps: list[WorkflowStep] = []

        # Callbacks (set by BrowserWorker)
        self.on_step_recorded: Callable[[WorkflowStep], None] | None = None
        self.on_hover: Callable[[dict], None] | None = None
        self.on_capture: Callable[[dict], None] | None = None
        self.on_cancel: Callable[[], None] | None = None
        self.on_log: Callable[[str], None] | None = None
        self.on_error: Callable[[str], None] | None = None

        # Track if functions are exposed
        self._functions_exposed = False

    # ═══════════════════════════════════════════════════════════
    # Recording
    # ═══════════════════════════════════════════════════════════

    def start_recording(self):
        """Inject recorder JS and activation flag."""
        if self.is_recording:
            return

        self.recorded_steps = []
        self._expose_functions_if_needed()

        # Activate recorder
        self.page.evaluate("window.__webGoToolRecorderActive = true;")
        self.page.evaluate(RECORDER_JS)
        self.is_recording = True
        logger.info("Recorder JS injected and active")

    def stop_recording(self) -> list[WorkflowStep]:
        """Deactivate recorder and return captured steps."""
        if not self.is_recording:
            return self.recorded_steps

        self.is_recording = False
        try:
            self.page.evaluate("window.__webGoToolRecorderActive = false;")
        except Exception:
            pass

        steps = list(self.recorded_steps)
        self.recorded_steps = []
        logger.info("Recording stopped — %d steps", len(steps))
        return steps

    # ═══════════════════════════════════════════════════════════
    # Element Capture Overlay
    # ═══════════════════════════════════════════════════════════

    def inject_capture_overlay(self):
        """Inject the element capture overlay."""
        self._expose_functions_if_needed()
        self.page.evaluate(CAPTURE_OVERLAY_JS)
        self._capture_active = True
        logger.info("Capture overlay injected")

    def remove_capture_overlay(self):
        """Remove the capture overlay."""
        self._capture_active = False
        try:
            self.page.evaluate(CLEANUP_JS)
        except Exception as e:
            logger.warning("Cleanup JS error: %s", e)

    # ═══════════════════════════════════════════════════════════
    # Internal: expose_function
    # ═══════════════════════════════════════════════════════════

    def _expose_functions_if_needed(self):
        """Register JS→Python callback functions via expose_function."""
        if self._functions_exposed:
            return

        try:
            self.page.expose_function(
                "__webGoTool_onEvent", self._handle_event
            )
            self.page.expose_function(
                "__webGoTool_onHover", self._handle_hover
            )
            self.page.expose_function(
                "__webGoTool_onCapture", self._handle_capture
            )
            self.page.expose_function(
                "__webGoTool_onCancel", self._handle_cancel
            )
            self._functions_exposed = True
            logger.info("JS callback functions exposed")
        except Exception as e:
            # Functions might already be exposed from a previous injection
            logger.warning("expose_function may have failed (already exposed?): %s", e)
            self._functions_exposed = True

    # ═══════════════════════════════════════════════════════════
    # Callback handlers
    # ═══════════════════════════════════════════════════════════

    def _handle_event(self, step_json: str):
        """Callback from JS: parse event info, create WorkflowStep."""
        if not self.is_recording:
            return

        try:
            info = json.loads(step_json)
        except json.JSONDecodeError:
            logger.warning("Malformed event JSON: %s", step_json[:100])
            return

        event_type = info.get("event", "click")
        tag = info.get("tag", "")
        el_type = info.get("type", "")

        # Determine action from event + element
        if event_type == "input" or event_type == "change":
            if tag in ("input", "textarea") or el_type in ("text", "password", "email", "number", "search"):
                action = "input"
            elif tag == "select":
                action = "input"
            elif el_type in ("checkbox", "radio"):
                action = "click"
            else:
                action = "input"
        else:  # click
            if tag in ("a", "button") or el_type in ("submit", "button", "reset"):
                action = "click"
            elif tag == "select":
                action = "input"
            else:
                action = "click"

        # Build selector
        sel = ""
        if info.get("id"):
            sel = f"#{info['id']}"
        elif info.get("name"):
            sel = f'[name="{info["name"]}"]'
        else:
            sel = info.get("cssSelector", "") or info.get("xpath", "")

        step = WorkflowStep(
            action=action,
            params={
                "selector": sel,
                "selectorType": "css",
                "value": info.get("value", ""),
            },
            description=info.get("text", "") or f"{info.get('tag','')}>{info.get('id','')}",
        )

        self.recorded_steps.append(step)
        logger.info("Recorded: %s → %s", action, sel)

        if self.on_step_recorded:
            self.on_step_recorded(step)

    def _handle_hover(self, element_json: str):
        """Callback from capture overlay: element hover."""
        try:
            info = json.loads(element_json)
            if self.on_hover:
                self.on_hover(info)
        except json.JSONDecodeError:
            pass

    def _handle_capture(self, element_json: str):
        """Callback from capture overlay: element confirmed (click)."""
        try:
            info = json.loads(element_json)
            logger.info("Element captured: %s", info.get("cssSelector", ""))
            if self.on_capture:
                self.on_capture(info)
        except json.JSONDecodeError:
            pass

    def _handle_cancel(self):
        """Callback from capture overlay: Escape pressed."""
        logger.info("Capture cancelled via Escape")
        if self.on_cancel:
            self.on_cancel()
