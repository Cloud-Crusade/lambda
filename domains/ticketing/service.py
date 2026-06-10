"""대기열 순번 발급·조회 및 입장 토큰(JWT) 발급 로직."""
import os
from typing import Any

import jwt
import redis

from common.logging import getLogger
from common.secrets import get_secret_string

logger = getLogger("ticketing")

REDIS_HOST = os.environ.get("REDIS_HOST", "")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
# 예약 토큰 서명용 RSA 개인키 — Secrets Manager 시크릿 이름(값이 아닌 이름만 env 로 주입)
RESERVATION_SECRET_ID = os.environ.get("RESERVATION_SECRET_ID", "")
JWT_ALGORITHM = "RS256"
JWT_AUDIENCE = "reservation_waiting"
CACHE_TTL_SECONDS = 3600


class SigningKeyError(RuntimeError):
    """RS256 서명에 필요한 개인키(PEM)가 없거나 유효하지 않음 (설정 오류)."""


class QueueService:
    def __init__(self, redis_client: Any = None, signing_key: str | None = None) -> None:
        self._redis = redis_client or redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, decode_responses=True,
        )
        # 키는 Secrets 확장 캐시에서 조회(env 엔 시크릿 이름만). 콜드스타트에 PEM 검증 → 발급 시 모호한 500 회피
        raw_key = signing_key if signing_key is not None else self._fetchSigningKey()
        self._signing_key = self._loadSigningKey(raw_key)

    @staticmethod
    def _fetchSigningKey() -> str:
        if not RESERVATION_SECRET_ID:
            raise SigningKeyError("RESERVATION_SECRET_ID 환경변수가 비어 있습니다")
        return get_secret_string(RESERVATION_SECRET_ID)

    @staticmethod
    def _loadSigningKey(secret: str) -> str:
        if not secret:
            raise SigningKeyError(
                "예약 서명키가 비어 있습니다 — RS256 서명에는 RSA 개인키 PEM 이 필요합니다",
            )
        try:
            # PEM 파싱 가능 여부를 발급 전에 검증 (cryptography 는 RS256 런타임 레이어에 포함)
            from jwt.algorithms import RSAAlgorithm
            RSAAlgorithm(RSAAlgorithm.SHA256).prepare_key(secret)
        except Exception as error:
            raise SigningKeyError(
                f"예약 서명키가 유효한 RSA 개인키 PEM 이 아닙니다: {error}",
            ) from error
        return secret

    def issue(self, *, event_id: str, user_id: str) -> dict[str, Any]:
        cache_key = f"{event_id}:{user_id}"
        queue_number = self._redis.incr(f"queue:{event_id}")

        # 동일 user_id 재요청 시 기존 번호 반환 (원자적 선점 실패 → 기존 값 조회)
        if not self._redis.set(cache_key, queue_number, nx=True, ex=CACHE_TTL_SECONDS):
            queue_number = int(self._redis.get(cache_key))

        current_number = int(self._redis.get(f"current:{event_id}") or 0)
        remaining = queue_number - current_number

        logger.info(
            "queue_status: user_id=%s, event_id=%s, queue_number=%s, remaining=%s",
            user_id, event_id, queue_number, remaining,
        )

        if remaining <= 0:
            return self._completed(event_id=event_id, user_id=user_id)
        return self._waiting(queue_number=queue_number, remaining=remaining)

    def _completed(self, *, event_id: str, user_id: str) -> dict[str, Any]:
        token = jwt.encode(
            {"user_id": user_id, "event_id": event_id, "aud": JWT_AUDIENCE},
            self._signing_key,
            algorithm=JWT_ALGORITHM,
        )
        return {
            "code": "COMPLETED",
            "message": "입장 순번이 되었습니다.",
            "data": {"token": token},
        }

    def _waiting(self, *, queue_number: int, remaining: int) -> dict[str, Any]:
        return {
            "code": "WAITING",
            "message": "현재 대기열",
            "data": {"queue_number": queue_number, "remaining": remaining},
        }
