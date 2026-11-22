import logging
from logging.handlers import RotatingFileHandler


def configure_logging(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("nisha")
    if not logger.handlers:
        handler = RotatingFileHandler(
            data_dir / "nisha.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger
