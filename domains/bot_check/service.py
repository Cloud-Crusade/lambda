import os
from typing import Any

import redis


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

        try:
            blacklisted = self.redis_client.exists(f"bot:blacklist:{ip}") == 1
        except redis.RedisError:
            # Redis 장애 시 트래픽 차단보다 가용성 우선 — 봇이 일시 통과 허용
            blacklisted = False

        effect = "Deny" if blacklisted else "Allow"

        return {
            "principalId": ip,
            "policyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Action": "execute-api:Invoke",
                        "Effect": effect,
                        "Resource": event.get("methodArn", "*"),
                    }
                ],
            },
        }

    def _extract_ip(self, event: dict[str, Any]) -> str:
        ip = event.get("requestContext", {}).get("identity", {}).get("sourceIp")
        if not ip:
            raise ValueError("requestContext.identity.sourceIp 가 없습니다.")
        return ip
