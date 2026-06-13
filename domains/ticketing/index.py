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
# 인증 경로라 익스텐션 조회 타임아웃 짧게(authorizer 와 동일)
_SECRETS_TIMEOUT = 2

# /queue 는 API GW ANY→AWS_PROXY 라 OPTIONS·CORS 를 람다가 직접 처리
_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    # 폴링 시 매 GET 마다 프리플라이트 재발생 방지 — 같은 URL 프리플라이트를 10분 캐시
    "Access-Control-Max-Age": "600",
    "Content-Type": "application/json",
}

# 시크릿 조회(Secrets 확장)는 첫 invoke 때 lazy — 확장은 콜드스타트 INIT 시점엔 ready 가 아님(400)
_service: QueueService | None = None


def _get_service() -> QueueService:
    global _service
    if _service is None:
        _service = QueueService()
    return _service


def _user_id_from_token(event: dict[str, Any]) -> str:
    # 큐 라우트는 API GW authorization=NONE → 람다가 access token(HS256) 직접 검증 후 sub 추출.
    # 시크릿은 코드 캐시 없이 Secrets 확장 캐시만 신뢰(회전이 재배포 없이 반영) — authorizer 와 동일
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    token = headers.get("authorization", "").removeprefix("Bearer ").strip()
    payload = jwt.decode(
        token,
        get_secret_string(_AUTHORIZATION_SECRET_ID, timeout=_SECRETS_TIMEOUT),
        algorithms=["HS256"],
        options={"verify_aud": False},  # 인증 토큰 aud 규약 미정 — authorizer 와 동일
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("access 토큰이 아닙니다")
    user_id = payload.get("sub")
    if not user_id:
        raise jwt.InvalidTokenError("sub 클레임이 없습니다")
    return user_id


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": _CORS_HEADERS,
        "body": json.dumps(body, ensure_ascii=False),
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    # CORS 프리플라이트는 인증/바디 없이 즉시 허용 (Authorization 헤더가 실리지 않음)
    if (event.get("httpMethod") or "").upper() == "OPTIONS":
        return {"statusCode": 204, "headers": _CORS_HEADERS, "body": ""}

    # event_id 누락 시 빈 키(queue:/current:) 공유로 이벤트 간 충돌 → 빠르게 400
    event_id = (event.get("pathParameters") or {}).get("event_id") or ""
    if not event_id:
        return _response(400, {"code": "BAD_REQUEST", "message": "event_id 가 필요합니다"})

    try:
        user_id = _user_id_from_token(event)
    except jwt.InvalidTokenError:
        return _response(401, {"code": "UNAUTHORIZED", "message": "유효하지 않은 토큰입니다"})

    result = _get_service().issue(event_id=event_id, user_id=user_id)
    return _response(200, result)
