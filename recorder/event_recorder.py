"""Event Recorder — injects JS into the page to capture user interactions.

Uses a polling-based approach instead of expose_function:
- JS stores events in window.__wgt_eventQueue
- Python polls via page.evaluate() to drain the queue
This avoids Playwright's greenlet cross-thread issue with expose_function.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from playwright.sync_api import Page

from flows.schema import WorkflowStep

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# JavaScript: Recorder injection (polling-based, no expose_function)
# ═══════════════════════════════════════════════════════════════

RECORDER_JS = r"""
(function() {
    if (window.__webGoToolRecorderInstalled) return;
    window.__webGoToolRecorderInstalled = true;
    window.__wgt_eventQueue = [];  // Python polls this array

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

    function pushEvent(info) {
        window.__wgt_eventQueue.push(info);
    }

    // --- Click Recording ---
    document.addEventListener('click', function(e) {
        if (!window.__webGoToolRecorderActive) return;
        const info = getElementInfo(e.target);
        if (!info) return;
        info.event = 'click';
        info.timestamp = Date.now();
        pushEvent(info);
    }, true);

    // --- Input Recording (debounced per element) ---
    document.addEventListener('input', function(e) {
        if (!window.__webGoToolRecorderActive) return;
        const el = e.target;
        if (!el || !el.matches('input,textarea,[contenteditable="true"]')) return;
        // Debounce marker
        const key = '__wgt_lastInput';
        if (el[key]) return;  // Already queued for this element
        el[key] = true;
        setTimeout(function() { el[key] = false; }, 500);
        const info = getElementInfo(el);
        if (!info) return;
        info.value = el.value || el.textContent || '';
        info.event = 'input';
        info.timestamp = Date.now();
        pushEvent(info);
    }, true);

    // --- Change Recording ---
    document.addEventListener('change', function(e) {
        if (!window.__webGoToolRecorderActive) return;
        const el = e.target;
        if (!el || !el.matches('select,input[type="checkbox"],input[type="radio"]')) return;
        const info = getElementInfo(el);
        if (!info) return;
        info.value = el.value || (el.checked ? 'checked' : 'unchecked');
        info.event = 'change';
        info.timestamp = Date.now();
        pushEvent(info);
    }, true);

    console.log('[WebGoTool] Recorder JS installed (polling mode)');
})();
"""

# ═══════════════════════════════════════════════════════════════
# JavaScript: Element capture overlay (polling-based)
# ═══════════════════════════════════════════════════════════════

CAPTURE_OVERLAY_JS = r"""
(function() {
    const old = document.getElementById('__wgt_overlay');
    if (old) old.remove();

    window.__wgt_capture_active = true;
    window.__wgt_capture_data = null;  // Python polls this

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
                _type: 'hover',
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
            window.__wgt_capture_data = JSON.stringify(info);
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
                _type: 'capture',
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
            window.__wgt_capture_data = JSON.stringify(info);
        }
        cleanup();
    }, true);

    function cleanup() {
        window.__wgt_capture_active = false;
        if (lastEl) { lastEl.style.outline = lastEl.__wgt_outline || ''; lastEl = null; }
        if (overlay.parentNode) overlay.remove();
        // Mark capture as cancelled if no capture event was set
        if (!window.__wgt_capture_data || JSON.parse(window.__wgt_capture_data)._type !== 'capture') {
            window.__wgt_capture_data = JSON.stringify({_type: 'cancel'});
        }
    }

    document.addEventListener('keydown', function handler(e) {
        if (e.key === 'Escape') {
            window.__wgt_capture_data = JSON.stringify({_type: 'cancel'});
            cleanup();
            document.removeEventListener('keydown', handler);
        }
    });

    document.body.appendChild(overlay);
    console.log('[WebGoTool] Capture overlay installed');
})();
"""

# ═══════════════════════════════════════════════════════════════
# Cleanup script
# ═══════════════════════════════════════════════════════════════

CLEANUP_JS = """
(function() {
    window.__webGoToolRecorderActive = false;
    window.__webGoToolRecorderInstalled = false;
    window.__wgt_eventQueue = [];
    window.__wgt_capture_data = null;
    window.__wgt_capture_active = false;
    const overlay = document.getElementById('__wgt_overlay');
    if (overlay) overlay.remove();
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
    """Injects JS into the page and polls for interaction events."""

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

        self._js_installed = False

    # ═══════════════════════════════════════════════════════════
    # Recording
    # ═══════════════════════════════════════════════════════════

    def start_recording(self):
        """Inject recorder JS and activation flag."""
        if self.is_recording:
            return

        self.recorded_steps = []

        # Install recorder JS if not already on this page
        if not self._js_installed:
            self.page.evaluate(RECORDER_JS)
            self._js_installed = True

        # Clear any stale events and activate
        self.page.evaluate("""
            window.__wgt_eventQueue = [];
            window.__webGoToolRecorderActive = true;
        """)
        self.is_recording = True
        logger.info("Recorder JS injected and active (polling mode)")

    def stop_recording(self) -> list[WorkflowStep]:
        """Deactivate recorder and return captured steps."""
        if not self.is_recording:
            return self.recorded_steps

        self.is_recording = False

        # Drain any remaining events from the queue
        self._drain_event_queue()

        try:
            self.page.evaluate("window.__webGoToolRecorderActive = false;")
        except Exception:
            pass

        steps = list(self.recorded_steps)
        self.recorded_steps = []
        logger.info("Recording stopped — %d steps", len(steps))
        return steps

    def _drain_event_queue(self):
        """Poll the JS event queue and process pending events."""
        if not self._js_installed:
            return
        try:
            events_json = self.page.evaluate(
                "JSON.stringify(window.__wgt_eventQueue || []);"
            )
            self.page.evaluate("window.__wgt_eventQueue = [];")

            if events_json:
                events = json.loads(events_json)
                for info in events:
                    self._process_event(info)
        except Exception as e:
            pass  # Page might be in transition

    def _process_event(self, info: dict):
        """Process a single event from the JS queue."""
        event_type = info.get("event", "click")
        tag = info.get("tag", "")
        el_type = info.get("type", "")

        # Determine action from event + element
        if event_type in ("input", "change"):
            if tag in ("input", "textarea") or el_type in ("text", "password", "email", "number", "search"):
                action = "input"
            elif tag == "select":
                action = "input"
            else:
                action = "click"
        else:  # click
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
            description=info.get("text", "") or f"{info.get('tag','')}#{info.get('id','')}",
        )

        self.recorded_steps.append(step)
        logger.info("Recorded: %s → %s", action, sel)

        if self.on_step_recorded:
            self.on_step_recorded(step)

    # ═══════════════════════════════════════════════════════════
    # Element Capture Overlay
    # ═══════════════════════════════════════════════════════════

    def inject_capture_overlay(self):
        """Inject the element capture overlay."""
        self.page.evaluate(CAPTURE_OVERLAY_JS)
        self._js_installed = False  # Reset so recorder can be re-installed later
        self._capture_active = True
        logger.info("Capture overlay injected (polling mode)")

    def remove_capture_overlay(self):
        """Remove the capture overlay."""
        self._capture_active = False
        try:
            self.page.evaluate(CLEANUP_JS)
        except Exception:
            pass
        self._js_installed = False

    def poll_capture(self):
        """Check if a capture event happened (called by timer)."""
        if not self._capture_active:
            return
        try:
            data_json = self.page.evaluate(
                "JSON.stringify(window.__wgt_capture_data || null);"
            )
            if not data_json or data_json == "null":
                # No event yet, emit latest hover if available
                return

            info = json.loads(data_json)
            if not info:
                return

            msg_type = info.get("_type", "")

            if msg_type == "capture":
                # Clear so we don't re-emit
                self.page.evaluate("window.__wgt_capture_data = null;")
                self._capture_active = False
                if self.on_capture:
                    self.on_capture(info)

            elif msg_type == "cancel":
                self.page.evaluate("window.__wgt_capture_data = null;")
                self._capture_active = False
                if self.on_cancel:
                    self.on_cancel()

            elif msg_type == "hover":
                if self.on_hover:
                    self.on_hover(info)

        except Exception:
            pass

    def poll_recording(self):
        """Called by BrowserWorker timer to flush event queue during recording."""
        if self.is_recording:
            self._drain_event_queue()
        if self._capture_active:
            self.poll_capture()
