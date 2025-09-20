# app/core/logging.py
import logging
import sys
import colorlog

def configure_logging(level=logging.INFO):
    handler = colorlog.StreamHandler(sys.stdout)
    handler.setFormatter(
        colorlog.ColoredFormatter(
            "%(log_color)s%(asctime)s %(levelname)-8s [%(name)s]%(reset)s %(message)s",
            datefmt="%H:%M:%S",
            log_colors={
                "DEBUG": "cyan",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "bold_red",
            },
        )
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = [handler]

    # Silence overly chatty libs if needed
    logging.getLogger("uvicorn.error").setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(level)
    logging.getLogger("pymongo").setLevel(logging.WARNING)
