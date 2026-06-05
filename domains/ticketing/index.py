"""ticketing 도메인 단일 진입점."""
import json
from typing import Any

from domains.ticketing.service import QueueService

_service = QueueService()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    result = _service.issue(
        event_id=event.get("event_id", "test-event"),
        user_id=event.get("user_id", ""),
    )
    return {
        "statusCode": 200,
        "body": json.dumps(result, ensure_ascii=False),
    }
