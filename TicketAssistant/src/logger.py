"""日志系统：控制台 + 文件轮转。"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logger(name: str = "ticket_assistant", level: str = "INFO") -> logging.Logger:
    """
    初始化日志器。
    :param name: logger 名称
    :param level: DEBUG / INFO / WARNING / ERROR
    """
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "ticket_assistant.log"

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger
