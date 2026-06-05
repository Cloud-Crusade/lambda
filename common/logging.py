"""도메인 공통 로깅 — 모든 Lambda 가 동일한 로거 설정을 공유한다."""
import logging


def getLogger(name: str = "lambda") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    return logger
