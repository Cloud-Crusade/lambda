"""captcha 도메인 단일 진입점 — ALTCHA PoW 챌린지 발급(API Gateway proxy)."""
import json
from typing import Any

from domains.captcha.service import CaptchaService

_service = CaptchaService()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    challenge = _service.issueChallenge()
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(challenge, ensure_ascii=False),
    }
