"""captcha 도메인 단일 진입점 — ALTCHA PoW 챌린지 발급(API Gateway proxy)."""
import json
import os
from typing import Any

from common.secrets import get_secret_string

try:
    from .service import CaptchaConfigError, CaptchaService  # 패키지 로드(repo·테스트)
except ImportError:
    from service import CaptchaConfigError, CaptchaService  # 평면 zip(Lambda)

_CAPTCHA_SECRET_ID = os.environ.get("CAPTCHA_SECRET_ID", "")

# 공개 경로지만 클라가 Authorization/Reservation 을 함께 실어 보냄 → 프리플라이트 허용 필요
_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Reservation, Content-Type",
    "Access-Control-Max-Age": "600",
    "Content-Type": "application/json",
}

# 시크릿 조회(Secrets 확장)는 첫 invoke 때 lazy — 확장은 콜드스타트 INIT 시점엔 ready 가 아님(크래시 회피)
_service: CaptchaService | None = None


def _get_service() -> CaptchaService:
    global _service
    if _service is None:
        if not _CAPTCHA_SECRET_ID:
            raise CaptchaConfigError("CAPTCHA_SECRET_ID 환경변수가 없습니다")
        _service = CaptchaService(secret=get_secret_string(_CAPTCHA_SECRET_ID))
    return _service


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    if (event.get("httpMethod") or "").upper() == "OPTIONS":
        return {"statusCode": 204, "headers": _CORS_HEADERS, "body": ""}

    challenge = _get_service().issue_challenge()
    return {
        "statusCode": 200,
        "headers": _CORS_HEADERS,
        "body": json.dumps(challenge, ensure_ascii=False),
    }
