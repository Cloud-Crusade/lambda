"""ticketing 도메인 단일 진입점."""
import json
from typing import Any

try:
    from .service import QueueService  # 패키지 로드(repo·테스트)
except ImportError:
    from service import QueueService  # 평면 zip(Lambda)

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
