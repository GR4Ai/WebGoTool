"""Chrome browser lifecycle — launch, CDP connect, page management."""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import tempfile
import time
from typing import Optional

from playwright.sync_api import sync_playwright, Browser, Page, Playwright

logger = logging.getLogger(__name__)

DEFAULT_CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DEFAULT_DEBUG_PORT = 9222


def _is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is already in use (i.e., Chrome debugging is running)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        result = sock.connect_ex((host, port))
        return result == 0
    except Exception:
        return False
    finally:
        sock.close()


class ChromeManager:
    """Manages Chrome browser lifecycle and CDP connection via Playwright."""

    def __init__(
        self,
        chrome_path: str | None = None,
        port: int = DEFAULT_DEBUG_PORT,
        user_data_dir: str | None = None,
    ):
        self.chrome_path = chrome_path or DEFAULT_CHROME_PATH
        self.port = port
        self.user_data_dir = user_data_dir

        # Runtime state
        self.chrome_process: subprocess.Popen | None = None
        self._playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.page: Page | None = None
        self._owned_process = False

    @property
    def is_connected(self) -> bool:
        """Check if browser connection is alive."""
        if self.browser is None or self.page is None:
            return False
        try:
            # Quick health check
            self.page.title()
            return True
        except Exception:
            return False

    def launch_chrome(self) -> bool:
        """Launch Chrome with --remote-debugging-port.

        If a debugging port is already open, reuse that instance.
        Otherwise, launch a NEW Chrome instance alongside any existing one
        using a separate temporary profile (does NOT close existing Chrome).
        Returns True if Chrome is running with the debug port.
        """
        # Check if Chrome debugging is already running
        if _is_port_open(self.port):
            logger.info("Chrome debugging already active on port %d, reusing", self.port)
            return True

        # Use a temporary profile → allows running alongside user's normal Chrome
        if not self.user_data_dir:
            self.user_data_dir = os.path.join(
                tempfile.gettempdir(), "webgotool_chrome_profile"
            )
            os.makedirs(self.user_data_dir, exist_ok=True)

        # Build launch command
        cmd = [
            self.chrome_path,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]

        logger.info("Launching Chrome with separate profile: %s", " ".join(cmd))

        try:
            self.chrome_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._owned_process = True

            # Wait for Chrome's debugging server to start
            for attempt in range(15):
                if _is_port_open(self.port):
                    logger.info("Chrome debugging port %d ready after %d attempts",
                                self.port, attempt + 1)
                    return True
                time.sleep(0.5)

            logger.error("Chrome debugging port %d did not become available", self.port)
            return False

        except FileNotFoundError:
            logger.error("Chrome not found at %s", self.chrome_path)
            return False
        except Exception as e:
            logger.exception("Failed to launch Chrome: %s", e)
            return False

    def connect_cdp(self) -> bool:
        """Connect Playwright to Chrome via CDP.

        Returns True if connected and a page is available.
        """
        if not _is_port_open(self.port):
            logger.error("Port %d is not open — launch Chrome first", self.port)
            return False

        try:
            self._playwright = sync_playwright().start()
            cdp_url = f"http://127.0.0.1:{self.port}"

            logger.info("Connecting to Chrome via CDP: %s", cdp_url)
            self.browser = self._playwright.chromium.connect_over_cdp(cdp_url)
            logger.info("Connected to Chrome (contexts: %d)", len(self.browser.contexts))

            # Get the active page
            self.page = self._get_active_page()

            if self.page is None:
                # No pages open — create a blank one
                logger.info("No pages open, creating about:blank")
                default_context = self.browser.contexts[0] if self.browser.contexts else None
                if default_context:
                    self.page = default_context.new_page()

            if self.page:
                logger.info("Active page: %s", self.page.url)
                return True
            else:
                logger.error("Could not obtain a page reference")
                return False

        except Exception as e:
            logger.exception("CDP connection failed: %s", e)
            return False

    def _get_active_page(self) -> Page | None:
        """Return the currently active/frontmost page in Chrome."""
        if not self.browser or not self.browser.contexts:
            return None

        for context in self.browser.contexts:
            pages = context.pages
            if pages:
                # Return the last page (usually the most recently active)
                return pages[-1]

        return None

    def refresh_page(self) -> Page | None:
        """Refresh the page reference (after user switches tabs)."""
        self.page = self._get_active_page()
        if self.page:
            logger.info("Refreshed page: %s", self.page.url)
        return self.page

    def new_cdp_session(self):
        """Create a raw CDP session for DevTools commands."""
        if self.browser and self.browser.contexts:
            return self.browser.contexts[0].new_cdp_session(self.page)
        raise RuntimeError("No browser context available")

    def send_cdp(self, method: str, params: dict | None = None) -> dict:
        """Send a raw CDP command and return the result."""
        session = self.new_cdp_session()
        try:
            return session.send(method, params)
        finally:
            session.detach()

    def close(self):
        """Disconnect Playwright. Optionally terminate the Chrome process."""
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
            self.browser = None

        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        if self._owned_process and self.chrome_process:
            try:
                self.chrome_process.terminate()
                self.chrome_process.wait(timeout=5)
            except Exception:
                pass
            self.chrome_process = None
            self._owned_process = False

        self.page = None
        logger.info("Chrome manager closed")
