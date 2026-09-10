import logging, os, sys
from pathlib import Path


def get_logger(name: str = "fantasy", level: str = None, logfile: str = None):
    lvl = (level or os.getenv("LOG_LEVEL") or "INFO").upper()
    logger = logging.getLogger(name)
    if logger.handlers:  # already configured
        logger.setLevel(lvl)
        return logger

    logger.setLevel(lvl)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s", datefmt="%H:%M:%S"
    )

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.setLevel(lvl)
    logger.addHandler(ch)

    lf = logfile or os.getenv("LOG_FILE")
    if lf:
        Path(lf).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(lf, encoding="utf-8")
        fh.setFormatter(fmt)
        fh.setLevel(lvl)
        logger.addHandler(fh)

    return logger
