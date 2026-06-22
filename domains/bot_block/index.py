"""Bot Block 이벤트 수신 Lambda."""

from typing import Any

try:
    from .service import BotBlockService
except ImportError:
    from service import BotBlockService


_service = BotBlockService()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return _service.process(event)