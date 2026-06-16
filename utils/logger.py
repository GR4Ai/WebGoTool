"""Logging configuration with rotating file handler and Qt signal bridge."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional


class QtLogHandler(logging.Handler):
    """Custom handler that emits log records via a callback for the UI log panel."""

    def __init__(self, level: int = logging.NOTSET):
        super().__init__(level)
        self._callback = None  # callable(str) or Signal

    def set_callback(self, callback):
        """Set the output callback — a Qt Signal or a plain callable(str)."""
        self._callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        cb = self._callback
        if cb is None:
            return
        if hasattr(cb, "emit"):
            cb.emit(msg)
        else:
            cb(msg)


_qt_handler: Optional[QtLogHandler] = None


def get_qt_handler() -> Optional[QtLogHandler]:
    """Return the global QtLogHandler instance."""
    return _qt_handler


def setup_logging(log_dir: str = "logs", level: int = logging.DEBUG) -> logging.Logger:
    """Configure file + console + Qt logging.

    Args:
        log_dir: Directory for log files.
        level: Log level for file/console handlers.

    Returns:
        Root logger.
    """
    global _qt_handler

    os.makedirs(log_dir, exist_ok=True)

    log_format = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Remove existing handlers to avoid duplicates on re-init
    root_logger.handlers.clear()

    # File handler (rotating, 5MB, 3 backups)
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "app.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(log_format)
    root_logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(log_format)
    root_logger.addHandler(console_handler)

    # Qt handler (connects to UI log panel)
    _qt_handler = QtLogHandler(level)
    _qt_handler.setFormatter(log_format)
    root_logger.addHandler(_qt_handler)

    return root_logger
