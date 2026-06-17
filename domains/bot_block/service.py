import json
import os
from typing import Any

import redis


class BotBlockService:
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
        self.blacklist_ttl_seconds = int(os.environ.get("BLACKLIST_TTL_SECONDS", "3600"))

    def process(self, event: dict[str, Any]) -> dict[str, Any]:
        ip = self._extract_ip(event)
        key = f"bot:blacklist:{ip}"

        self.redis_client.set(
            key,
            json.dumps(
                {
                    "reason": "bot-detection",
                    "source": event.get("source"),
                    "detail_type": event.get("detail-type"),
                },
                ensure_ascii=False,
            ),
            ex=self.blacklist_ttl_seconds,
        )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Bot IP blocked",
                    "ip": ip,
                    "key": key,
                    "ttl": self.blacklist_ttl_seconds,
                },
                ensure_ascii=False,
            ),
        }

    def _extract_ip(self, event: dict[str, Any]) -> str:
        detail = event.get("detail") or {}

        ip = (
            detail.get("ip")
            or detail.get("client_ip")
            or detail.get("clientIp")
            or detail.get("source_ip")
            or detail.get("sourceIp")
        )

        if not ip:
            raise ValueError("EventBridge event detail에 IP 정보가 없습니다.")

        return ip