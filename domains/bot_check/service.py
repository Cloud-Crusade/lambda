import os
from typing import Any

import redis

_COUNT_WINDOW_SECONDS = 60
_COUNT_THRESHOLD = 15
_BLACKLIST_TTL_SECONDS = 3600
_TARGET_PREFIXES = ("/reservations", "/payments")


class BotCheckService:
    def __init__(self) -> None:
        redis_host = os.environ.get("REDIS_HOST")
        if not redis_host:
            raise RuntimeError("REDIS_HOST 환경변수가 설정되지 않았습니다.")

        self.redis_client = redis.Redis(
            host=redis_host,
            port=int(os.environ.get("REDIS_PORT", "6379")),
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )

    def check(self, event: dict[str, Any]) -> dict[str, Any]:
        ip = self._extract_ip(event)
        method_arn = event.get("methodArn", "*")

        try:
            if self._is_target_path(event) and self._track_and_block(ip):
                return _policy(ip, "Deny", method_arn)

            blacklisted = self.redis_client.exists(f"bot:blacklist:{ip}") == 1
        except redis.RedisError:
            # Redis 장애 시 트래픽 차단보다 가용성 우선 — 봇이 일시 통과 허용
            blacklisted = False

        return _policy(ip, "Deny" if blacklisted else "Allow", method_arn)

    def _is_target_path(self, event: dict[str, Any]) -> bool:
        path = event.get("path", "")
        return any(path.startswith(prefix) for prefix in _TARGET_PREFIXES)

    def _track_and_block(self, ip: str) -> bool:
        count_key = f"bot:count:{ip}"
        # 기존: count==1 시에만 expire() 호출 → Lambda 크래시 시 TTL 미설정으로 키 영구 잔류.
        # pipeline + EXPIRE NX(Redis 7.0+)로 원자성 보장, 고정 윈도우 유지.
        pipe = self.redis_client.pipeline()
        pipe.incr(count_key)
        pipe.expire(count_key, _COUNT_WINDOW_SECONDS, nx=True)
        count, _ = pipe.execute()
        if count > _COUNT_THRESHOLD:
            self.redis_client.set(f"bot:blacklist:{ip}", "1", ex=_BLACKLIST_TTL_SECONDS)
            return True
        return False

    def _extract_ip(self, event: dict[str, Any]) -> str:
        ip = event.get("requestContext", {}).get("identity", {}).get("sourceIp")
        if not ip:
            raise ValueError("requestContext.identity.sourceIp 가 없습니다.")
        return ip


def _policy(principal_id: str, effect: str, method_arn: str) -> dict[str, Any]:
    return {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": method_arn,
                }
            ],
        },
    }
