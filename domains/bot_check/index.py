"""Bot 블랙리스트 확인 Lambda — API Gateway REQUEST authorizer."""

from typing import Any

try:
    from .service import BotCheckService
except ImportError:
    from service import BotCheckService


_service = BotCheckService()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return _service.check(event)
