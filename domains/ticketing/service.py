"""대기열 순번 발급·조회 및 입장 토큰(JWT) 발급 로직."""
import os
from typing import Any

import jwt
import redis

from common.logging import getLogger

logger = getLogger("ticketing")

REDIS_HOST = os.environ.get("REDIS_HOST", "")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
# JWT_SECRET 은 terraform 이 생성한 예약 RSA 개인키(PEM) — 검증측(authorizer)은 S3 공개키로 RS256 검증
JWT_SECRET = os.environ.get("JWT_SECRET", "")
JWT_ALGORITHM = "RS256"
JWT_AUDIENCE = "reservation_waiting"
CACHE_TTL_SECONDS = 3600


class QueueService:
    def __init__(self, redis_client: Any = None) -> None:
        self._redis = redis_client or redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, decode_responses=True,
        )

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
            JWT_SECRET,
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
