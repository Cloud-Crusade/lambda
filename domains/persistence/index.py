"""persistence 도메인 단일 진입점."""
from typing import Any

from domains.persistence.consumer import PersistenceConsumer

_consumer = PersistenceConsumer()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return _consumer.consume(event)
