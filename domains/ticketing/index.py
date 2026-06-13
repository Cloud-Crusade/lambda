"""ticketing 도메인 단일 진입점."""
import json
import os
from typing import Any

import jwt
from common.secrets import get_secret_string

try:
    from .service import QueueService  # 패키지 로드(repo·테스트)
except ImportError:
    from service import QueueService  # 평면 zip(Lambda)

_AUTHORIZATION_SECRET_ID = os.environ.get("AUTHORIZATION_SECRET_ID", "")

# 시크릿 조회(Secrets 확장)는 첫 invoke 때 lazy — 확장은 콜드스타트 INIT 시점엔 ready 가 아님(400)
_service: QueueService | None = None
_auth_secret: str | None = None


def _get_service() -> QueueService:
    global _service
    if _service is None:
        _service = QueueService()
    return _service


def _user_id_from_token(event: dict[str, Any]) -> str:
    # 큐 라우트는 API GW authorization=NONE → 람다가 access token(HS256) 직접 검증 후 sub 추출
    global _auth_secret
    if _auth_secret is None:
        _auth_secret = get_secret_string(_AUTHORIZATION_SECRET_ID)
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    token = headers.get("authorization", "").removeprefix("Bearer ").strip()
    payload = jwt.decode(token, _auth_secret, algorithms=["HS256"])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("access 토큰이 아닙니다")
    return payload["sub"]


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    event_id = (event.get("pathParameters") or {}).get("event_id", "")
    try:
        user_id = _user_id_from_token(event)
    except jwt.InvalidTokenError:
        return {
            "statusCode": 401,
            "body": json.dumps(
                {"code": "UNAUTHORIZED", "message": "유효하지 않은 토큰입니다"},
                ensure_ascii=False,
            ),
        }

    result = _get_service().issue(event_id=event_id, user_id=user_id)
    return {
        "statusCode": 200,
        "body": json.dumps(result, ensure_ascii=False),
    }
