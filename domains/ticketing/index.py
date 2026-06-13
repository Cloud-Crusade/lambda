"""ticketing 도메인 단일 진입점."""
import json
from typing import Any

try:
    from .service import QueueService  # 패키지 로드(repo·테스트)
except ImportError:
    from service import QueueService  # 평면 zip(Lambda)

# 시크릿 조회(Secrets 확장)는 첫 invoke 때 lazy — 확장은 콜드스타트 INIT 시점엔 ready 가 아님(400)
_service: QueueService | None = None


def _get_service() -> QueueService:
    global _service
    if _service is None:
        _service = QueueService()
    return _service


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    result = _get_service().issue(
        event_id=event.get("event_id", "test-event"),
        user_id=event.get("user_id", ""),
    )
    return {
        "statusCode": 200,
        "body": json.dumps(result, ensure_ascii=False),
    }
