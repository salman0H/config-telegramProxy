"""Shared UTC logging; credentials are redacted before reaching any handler."""
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler


class SecretFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        for name in ("TELEGRAM_BOT_TOKEN", "DB_PASSWORD"):
            secret = os.environ.get(name)
            if secret:
                message = message.replace(secret, "[REDACTED]")
        record.msg, record.args = message, ()
        return True


def configure_logging():
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level, logging.INFO)
    if not isinstance(level, int):
        level = logging.INFO
    formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(name)s %(message)s", "%Y-%m-%dT%H:%M:%S")
    formatter.converter = time.gmtime
    handlers = [logging.StreamHandler(sys.stderr)]
    log_file = os.environ.get("LOG_FILE")
    if log_file:
        handlers.append(RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"))
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(SecretFilter())
    logging.basicConfig(level=level, handlers=handlers, force=True)
