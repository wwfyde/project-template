import logging.config
from typing import Literal


def setup_logging(level: Literal["DEBUG", "INFO", "WARNING"] = "INFO") -> None:
    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
                # "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "access": {
                "format": "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
                # "format": '%(asctime)s | %(levelname)-8s | "%(request_line)s" | %(status_code)s',
                # "format": '%(asctime)s | %(levelname)-8s | %(client_addr)s | "%(request_line)s" | %(status_code)s',
                # "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": level,
                "formatter": "default",
            },
            "access_console": {
                "class": "logging.StreamHandler",
                "level": level,
                "formatter": "access",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            # 你的业务日志
            "api": {
                "handlers": ["console"],
                "level": level,
                "propagate": False,
            },
            # Uvicorn 自身日志
            "uvicorn": {
                "handlers": ["console"],
                "level": level,
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["console"],
                "level": level,
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["access_console"],
                "level": level,
                "propagate": False,
            },
        },
        "root": {
            "handlers": ["console"],
            "level": level,
        },
    }
    logging.config.dictConfig(logging_config)
