"""Project logging never records tool payloads or credentials."""
import functools
import logging
import os
import re
import time


class RedactingFormatter(logging.Formatter):
    def format(self, record):
        text = super().format(record)
        for name, value in os.environ.items():
            if value and len(value) >= 6 and any(part in name.upper() for part in ("KEY", "TOKEN", "PASSWORD", "SECRET")):
                text = text.replace(value, "[credential redacted]")
        return re.sub(r"(?i)(api[_-]?key|token|password|authorization)([=:\s]+)[^\s&]+",
                      r"\1\2[credential redacted]", text)


def get_logger(name="ai_chef"):
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = logging.StreamHandler()
        handler.setFormatter(RedactingFormatter("[%(asctime)s] %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def log_tool_call(func):
    logger = get_logger("ai_chef.tools")
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            logger.info("Tool completed name=%s elapsed_ms=%d", func.__name__, (time.perf_counter()-start)*1000)
            return result
        except Exception as exc:
            logger.error("Tool failed name=%s exception_type=%s", func.__name__, type(exc).__name__)
            raise
    return wrapper


def log_async_tool_call(func):
    logger = get_logger("ai_chef.tools")
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            logger.info("Tool completed name=%s elapsed_ms=%d", func.__name__, (time.perf_counter()-start)*1000)
            return result
        except Exception as exc:
            logger.error("Tool failed name=%s exception_type=%s", func.__name__, type(exc).__name__)
            raise
    return wrapper
