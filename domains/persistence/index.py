"""persistence 도메인 단일 진입점."""
from typing import Any

try:
    from .consumer import PersistenceConsumer  # 패키지 로드(repo·테스트)
except ImportError:
    from consumer import PersistenceConsumer  # 평면 zip(Lambda)

_consumer = PersistenceConsumer()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return _consumer.consume(event)
