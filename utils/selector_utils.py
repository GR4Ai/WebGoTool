"""Selector generation utilities.

Priority: id > name > data-testid > aria-label > unique CSS > XPath.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def generate_best_selector(element_info: dict[str, Any]) -> str:
    """Generate the best available CSS/XPath selector from element info.

    Args:
        element_info: Dict from JS getElementInfo with keys: id, name, className,
            cssSelector, xpath, attributes (with data-testid, aria-label, etc).

    Returns:
        Best selector string.
    """
    # Priority 1: id
    el_id = element_info.get("id", "").strip()
    if el_id:
        return f"#{el_id}"

    # Priority 2: name attribute
    name = element_info.get("name", "").strip()
    if name:
        return f'[name="{name}"]'

    # Priority 3: data-testid
    attrs = element_info.get("attributes", {})
    testid = attrs.get("data-testid", "").strip()
    if testid:
        return f'[data-testid="{testid}"]'

    # Priority 4: aria-label
    aria_label = attrs.get("aria-label", "").strip()
    if aria_label:
        return f'[aria-label="{aria_label}"]'

    # Priority 5: unique CSS class combination
    css = element_info.get("cssSelector", "").strip()
    if css:
        return css

    # Priority 6: XPath fallback
    xpath = element_info.get("xpath", "").strip()
    if xpath:
        return xpath

    return ""


def generate_all_selectors(element_info: dict[str, Any]) -> dict[str, str]:
    """Generate all possible selectors for an element.

    Returns:
        Dict with keys: id, name, css, xpath, data_testid, aria_label.
    """
    selectors: dict[str, str] = {}

    el_id = element_info.get("id", "").strip()
    if el_id:
        selectors["id"] = f"#{el_id}"

    name = element_info.get("name", "").strip()
    if name:
        selectors["name"] = f'[name="{name}"]'

    css = element_info.get("cssSelector", "").strip()
    if css:
        selectors["css"] = css

    xpath = element_info.get("xpath", "").strip()
    if xpath:
        selectors["xpath"] = xpath

    attrs = element_info.get("attributes", {})
    testid = attrs.get("data-testid", "").strip()
    if testid:
        selectors["data_testid"] = f'[data-testid="{testid}"]'

    aria_label = attrs.get("aria-label", "").strip()
    if aria_label:
        selectors["aria_label"] = f'[aria-label="{aria_label}"]'

    return selectors


def selectors_try_order(element_info: dict[str, Any]) -> list[str]:
    """Return selectors in priority order for trying during playback."""
    all_sel = generate_all_selectors(element_info)
    order = ["id", "name", "data_testid", "aria_label", "css", "xpath"]
    result = []
    for key in order:
        if key in all_sel:
            sel = all_sel[key]
            # Convert id-style to css-style
            if key == "id" and sel.startswith("#"):
                result.append(sel)
            else:
                result.append(sel)
    return result


def describe_element_info(element_info: dict[str, Any]) -> str:
    """Return a human-readable description of the element."""
    tag = element_info.get("tag", "unknown")
    el_id = element_info.get("id", "")
    name = element_info.get("name", "")
    text = element_info.get("text", "")
    cls = element_info.get("className", "")

    parts = [f"<{tag}>"]
    if el_id:
        parts.append(f"id={el_id}")
    if name:
        parts.append(f"name={name}")
    if cls:
        parts.append(f"class=\"{cls[:50]}\"")
    if text:
        parts.append(f"text=\"{text[:50]}\"")

    return " ".join(parts)
