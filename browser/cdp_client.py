"""Low-level CDP command wrappers for DOM inspection.

Used as a fallback when JS injection is not available.
"""

from __future__ import annotations

import ctypes
import logging
from typing import Any

logger = logging.getLogger(__name__)


class CDPClient:
    """Encapsulates CDP DOM commands for element inspection."""

    def __init__(self, session):
        """Initialize with a Playwright CDPSession."""
        self.session = session
        self._highlighted_node: int | None = None

    def get_node_at_location(self, x: int, y: int) -> dict[str, Any] | None:
        """Use CDP DOM.getNodeForLocation to find node at page coordinates.

        Returns dict with nodeId and backendNodeId, or None.
        """
        try:
            result = self.session.send("DOM.getNodeForLocation", {
                "x": x,
                "y": y,
                "includeUserAgentShadowDOM": True,
            })
            return result
        except Exception as e:
            logger.warning("DOM.getNodeForLocation failed at (%d,%d): %s", x, y, e)
            return None

    def describe_node(self, node_id: int) -> dict[str, Any] | None:
        """Use CDP DOM.describeNode to get full node info including attributes."""
        try:
            result = self.session.send("DOM.describeNode", {
                "nodeId": node_id,
                "depth": 1,
                "pierce": True,
            })
            return result.get("node", result)
        except Exception as e:
            logger.warning("DOM.describeNode failed for node %d: %s", node_id, e)
            return None

    def get_element_info(self, x: int, y: int) -> dict[str, Any] | None:
        """High-level method: get element at (x,y) and return structured info.

        Combines getNodeForLocation + describeNode.
        """
        location = self.get_node_at_location(x, y)
        if not location:
            return None

        node_id = location.get("nodeId")
        if not node_id:
            return None

        node_info = self.describe_node(node_id)
        if not node_info:
            return None

        attributes = {}
        attrs_list = node_info.get("attributes", [])
        # CDP attributes come as [key1, value1, key2, value2, ...]
        for i in range(0, len(attrs_list) - 1, 2):
            attributes[attrs_list[i]] = attrs_list[i + 1]

        return {
            "tag": node_info.get("localName", node_info.get("nodeName", "")).lower(),
            "id": attributes.get("id", ""),
            "name": attributes.get("name", ""),
            "className": attributes.get("class", ""),
            "type": attributes.get("type", ""),
            "text": "",
            "href": attributes.get("href", ""),
            "attributes": attributes,
            "xpath": self._build_xpath_from_attributes(attributes, node_info),
            "cssSelector": self._build_css_from_attributes(attributes, node_info),
        }

    def highlight_node(self, node_id: int):
        """Visually highlight an element using CDP Overlay."""
        try:
            self.session.send("Overlay.highlightNode", {
                "nodeId": node_id,
                "highlightConfig": {
                    "contentColor": {"r": 255, "g": 68, "b": 68, "a": 0.3},
                    "marginColor": {"r": 255, "g": 68, "b": 68, "a": 0.1},
                    "borderColor": {"r": 255, "g": 68, "b": 68, "a": 1.0},
                }
            })
            self._highlighted_node = node_id
        except Exception as e:
            logger.warning("Overlay.highlightNode failed: %s", e)

    def hide_highlight(self):
        """Remove CDP overlay highlight."""
        if self._highlighted_node is not None:
            try:
                self.session.send("Overlay.hideHighlight")
            except Exception:
                pass
            self._highlighted_node = None

    @staticmethod
    def screen_to_page_coords(
        screen_x: int, screen_y: int, chrome_hwnd: int
    ) -> tuple[int, int]:
        """Convert Windows screen coordinates to page-relative coordinates.

        Accounts for Chrome window position and title bar offset.
        Note: This is approximate due to DPI scaling and browser chrome.
        """
        user32 = ctypes.windll.user32

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        rect = RECT()
        user32.GetWindowRect(chrome_hwnd, ctypes.byref(rect))

        # Approximate title bar + toolbar height (~90px at 100% scaling)
        title_bar_height = 90
        page_x = screen_x - rect.left
        page_y = screen_y - rect.top - title_bar_height

        return max(0, page_x), max(0, page_y)

    @staticmethod
    def _build_xpath_from_attributes(attributes: dict, node_info: dict) -> str:
        """Build a simple XPath from element attributes."""
        node_name = node_info.get("localName", node_info.get("nodeName", ""))
        el_id = attributes.get("id", "")
        if el_id:
            return f'//*[@id="{el_id}"]'
        el_name = attributes.get("name", "")
        if el_name:
            return f'//{node_name}[@name="{el_name}"]'
        return f"//{node_name}"

    @staticmethod
    def _build_css_from_attributes(attributes: dict, node_info: dict) -> str:
        """Build a simple CSS selector from element attributes."""
        node_name = node_info.get("localName", node_info.get("nodeName", ""))
        el_id = attributes.get("id", "")
        if el_id:
            return f"#{el_id}"
        el_name = attributes.get("name", "")
        if el_name:
            return f'[{node_name}][name="{el_name}"]'
        el_class = attributes.get("class", "").strip()
        if el_class:
            first_cls = el_class.split()[0]
            return f"{node_name}.{first_cls}"
        return node_name
