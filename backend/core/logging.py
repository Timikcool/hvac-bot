"""Logging configuration for the application."""

import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from config import get_settings


def setup_logging() -> None:
    """Configure application logging with both console and file output."""
    settings = get_settings()

    # Set log level based on debug mode
    log_level = logging.DEBUG if settings.debug else logging.INFO

    # Create log directory if it doesn't exist
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    # Log file path with date
    log_file = log_dir / f"hvac_backend_{datetime.now().strftime('%Y-%m-%d')}.log"

    # Formatters
    console_format = "%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s"
    file_format = "%(asctime)s | %(levelname)-8s | %(name)-25s | %(funcName)s:%(lineno)d | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(console_format, datefmt=date_format))

    # File handler with rotation
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=settings.log_max_size_mb * 1024 * 1024,  # Convert MB to bytes
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)  # Always log DEBUG to file
    file_handler.setFormatter(logging.Formatter(file_format, datefmt=date_format))

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture all, handlers will filter
    root_logger.handlers.clear()  # Remove any existing handlers
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Set specific log levels for noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    
    # Silence Anthropic client DEBUG logs - they include full base64 image data!
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    logging.getLogger("anthropic._base_client").setLevel(logging.WARNING)
    
    # Silence OpenAI client DEBUG logs - they also include full base64 image data!
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("openai._base_client").setLevel(logging.WARNING)

    # Keep SQLAlchemy queries visible in debug mode
    if settings.debug:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
    else:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    # Log startup message
    startup_logger = logging.getLogger("startup")
    startup_logger.info(f"")
    startup_logger.info(f"╔══════════════════════════════════════════════════════════════")
    startup_logger.info(f"║ 🚀 HVAC AI Assistant Backend Starting")
    startup_logger.info(f"║ Log file: {log_file.absolute()}")
    startup_logger.info(f"║ Log level: {'DEBUG' if settings.debug else 'INFO'}")
    startup_logger.info(f"╚══════════════════════════════════════════════════════════════")


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name."""
    return logging.getLogger(name)


class LoggerMixin:
    """Mixin class to add logging to any class."""

    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(self.__class__.__name__)


def log_request(logger: logging.Logger, method: str, path: str, **kwargs: Any) -> None:
    """Log an incoming request."""
    extra_info = " | ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
    logger.info(f"REQUEST  | {method} {path}" + (f" | {extra_info}" if extra_info else ""))


def log_response(logger: logging.Logger, method: str, path: str, status: int, duration_ms: int) -> None:
    """Log an outgoing response."""
    logger.info(f"RESPONSE | {method} {path} | status={status} | duration={duration_ms}ms")


def log_error(logger: logging.Logger, error: Exception, context: str = "") -> None:
    """Log an error with context."""
    logger.error(f"ERROR | {context} | {type(error).__name__}: {error}", exc_info=True)
