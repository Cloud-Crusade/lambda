"""대기열 순번 발급·조회 및 입장 토큰(JWT) 발급 로직."""
import os
import time
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

# 토큰 버킷 입장 제어 — 토큰이 rate 로 차되 capacity 에서 상한(누적 무제한 방지 → lull 후 버스트도 capacity 까지만).
# rate·capacity 모두 오토스케일되는 reservation pod 수에 비례(다운스트림 수용량 추종).
QUEUE_PER_POD_ADMIT_PER_SECOND = float(os.environ.get("QUEUE_PER_POD_ADMIT_PER_SECOND", "10"))
QUEUE_PER_POD_BURST = float(os.environ.get("QUEUE_PER_POD_BURST", "20"))
# queue_number 가 1부터(incr)라 첫 명을 즉시 들이려면 초기 입장 ≥ 1
QUEUE_INITIAL_ADMIT = int(os.environ.get("QUEUE_INITIAL_ADMIT", "1"))
# reservation pod 하트비트 정렬셋(score=epoch). pod 가 ZADD, 큐가 만료분 제거 후 ZCARD 로 라이브 수 산정
POD_HEARTBEAT_KEY = "rsv:pods"
POD_HEARTBEAT_TTL_SECONDS = 30

# 입장 커서(current) 원자적 토큰버킷 전진 — 동시 폴링에도 정확. now 는 redis TIME(클럭 일원화).
# KEYS: current, tokens, tokens_ts, queue(issued)  ARGV: rate, capacity, initial
_ADMIT_LUA = """
local t = redis.call('TIME')
local now = tonumber(t[1])
local current = tonumber(redis.call('GET', KEYS[1]) or ARGV[3])
local tokens = tonumber(redis.call('GET', KEYS[2]) or ARGV[2])
local ts = tonumber(redis.call('GET', KEYS[3]) or now)
local issued = tonumber(redis.call('GET', KEYS[4]) or '0')
local rate = tonumber(ARGV[1])
local cap = tonumber(ARGV[2])
tokens = tokens + (now - ts) * rate
if tokens > cap then tokens = cap end
local waiters = issued - current
if waiters < 0 then waiters = 0 end
local admit = math.floor(tokens)
if admit > waiters then admit = waiters end
current = current + admit
tokens = tokens - admit
redis.call('SET', KEYS[1], current)
redis.call('SET', KEYS[2], tokens)
redis.call('SET', KEYS[3], now)
return current
"""


class SigningKeyError(RuntimeError):
    """RS256 서명에 필요한 개인키(PEM)가 없거나 유효하지 않음 (설정 오류)."""


class QueueService:
    def __init__(self, redis_client: Any = None, signing_key: str | None = None) -> None:
        self._redis = redis_client or redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, decode_responses=True,
        )
        self._admit = self._redis.register_script(_ADMIT_LUA)
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
        # 신규 user 만 번호 발급(incr). 재폴링은 캐시 번호 재사용 → 폴링마다 queue 카운터가
        # 부풀어 신규 유저 번호가 실인원보다 커지는(=배출이 못 따라잡는) 문제 방지
        existing = self._redis.get(cache_key)
        if existing is not None:
            queue_number = int(existing)
        else:
            queue_number = self._redis.incr(f"queue:{event_id}")
            # 동시 최초요청 race: 선점 실패 시 기존 값 사용
            if not self._redis.set(cache_key, queue_number, nx=True, ex=CACHE_TTL_SECONDS):
                queue_number = int(self._redis.get(cache_key))

        # 라이브 pod 수에 비례해 토큰버킷 rate·capacity 산정 후, current 를 원자적으로 전진
        pods = self._live_pod_count()
        admitted = int(self._admit(
            keys=[
                f"current:{event_id}",
                f"tokens:{event_id}",
                f"tokens_ts:{event_id}",
                f"queue:{event_id}",
            ],
            args=[
                pods * QUEUE_PER_POD_ADMIT_PER_SECOND,
                pods * QUEUE_PER_POD_BURST,
                QUEUE_INITIAL_ADMIT,
            ],
        ))
        remaining = queue_number - admitted

        logger.info(
            "queue_status: user_id=%s, event_id=%s, queue_number=%s, admitted=%s, pods=%s",
            user_id, event_id, queue_number, admitted, pods,
        )

        if remaining <= 0:
            return self._completed(event_id=event_id, user_id=user_id)
        return self._waiting(queue_number=queue_number, remaining=remaining)

    def _live_pod_count(self) -> int:
        # 만료(>TTL) 하트비트 제거 후 라이브 reservation pod 수. 하트비트 없으면 1(최소 배출 보장)
        now = int(time.time())
        self._redis.zremrangebyscore(POD_HEARTBEAT_KEY, 0, now - POD_HEARTBEAT_TTL_SECONDS)
        return max(1, self._redis.zcard(POD_HEARTBEAT_KEY))

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
