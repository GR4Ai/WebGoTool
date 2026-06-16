"""WebGoTool — Desktop Web Automation Tool.

A browser macro recorder/player that connects to the user's own Chrome
via remote debugging protocol (CDP), powered by Playwright + PySide6.
"""

import logging
import os
import sys
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt

from utils.logger import setup_logging
from ui.mainwindow import MainWindow


def _global_exception_hook(exc_type, exc_value, exc_tb):
    """Handle unhandled exceptions: log + show dialog."""
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logging.critical("Unhandled exception\n%s", tb_text)
    QMessageBox.critical(
        None,
        "Fatal Error",
        f"An unhandled error occurred:\n\n{exc_value}\n\n"
        "Check logs/app.log for details.",
    )
    sys.exit(1)


def main() -> None:
    """Application entry point."""
    # Configure logging
    setup_logging()

    logger = logging.getLogger(__name__)
    logger.info("Starting WebGoTool...")

    # Install global exception hook
    sys.excepthook = _global_exception_hook

    # Create Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("WebGoTool")
    app.setOrganizationName("WebGoTool")
    app.setStyle("Fusion")

    # Load QSS stylesheet
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(__file__))
    qss_path = os.path.join(base_dir, "resources", "style.qss")
    if os.path.exists(qss_path):
        try:
            with open(qss_path, "r", encoding="utf-8") as f:
                app.setStyleSheet(f.read())
            logging.getLogger(__name__).info("Stylesheet loaded from %s", qss_path)
        except Exception:
            pass

    # Enable high-DPI scaling (default in Qt6)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps)

    # Create and show main window
    window = MainWindow()
    window.show()

    logger.info("WebGoTool started successfully")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
