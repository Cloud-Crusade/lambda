"""captcha 도메인 단일 진입점 — ALTCHA PoW 챌린지 발급(API Gateway proxy)."""
import json
import os
from typing import Any

from common.secrets import get_secret_string
try:
    from .service import CaptchaConfigError, CaptchaService  # 패키지 로드(repo·테스트)
except ImportError:
    from service import CaptchaConfigError, CaptchaService  # 평면 zip(Lambda)

# 콜드스타트 1회 — 시크릿은 Secrets 확장 캐시에서 조회(env 에는 이름만 둔다)
_secret_id = os.environ.get("CAPTCHA_SECRET_ID")
if not _secret_id:
    raise CaptchaConfigError("CAPTCHA_SECRET_ID 환경변수가 없습니다")
_service = CaptchaService(secret=get_secret_string(_secret_id))


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    challenge = _service.issue_challenge()
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(challenge, ensure_ascii=False),
    }
