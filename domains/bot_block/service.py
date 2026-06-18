import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import boto3
import redis

_LOG_GROUP_NAME = os.environ.get("LOG_GROUP_NAME", "")
_LOOKBACK_SECONDS = 120
_QUERY_TIMEOUT_SECONDS = 25
_QUERY_POLL_INTERVAL = 2

# path 필드 기준 — /payments 는 /{proxy+} 경유라 resourcePath 불일치.
# 기존: cnt 필터 없이 sort+limit만 사용 → 1회 접근 정상 사용자도 오탐 가능.
# filter cnt > 30 추가로 최소 요청 횟수 미달 IP 제외.
_SUSPICIOUS_QUERY = """\
fields ip, status, path
| filter status = 429 or path like /\\/reservations/ or path like /\\/payments/
| stats count() as cnt by ip
| filter cnt > 30
| sort cnt desc
| limit 100"""


class BotBlockService:
    def __init__(self) -> None:
        if not _LOG_GROUP_NAME:
            raise RuntimeError("LOG_GROUP_NAME 환경변수가 설정되지 않았습니다.")

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
        self._logs = boto3.client("logs")

    def process(self, event: dict[str, Any]) -> dict[str, Any]:
        alarm_name, alarm_time = self._parse_alarm(event)

        end_time = int(alarm_time.timestamp())
        start_time = end_time - _LOOKBACK_SECONDS

        ips = self._query_suspicious_ips(start_time, end_time)

        if ips:
            self._store(ips, alarm_name)

        return {"alarm": alarm_name, "blocked": len(ips), "ips": ips}

    def _parse_alarm(self, event: dict[str, Any]) -> tuple[str, datetime]:
        detail = event.get("detail", {})
        alarm_name = detail.get("alarmName", "unknown")
        timestamp_str = detail.get("state", {}).get("timestamp", "")

        alarm_time = (
            datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            if timestamp_str
            else datetime.now(timezone.utc)
        )
        return alarm_name, alarm_time

    def _query_suspicious_ips(self, start_time: int, end_time: int) -> list[str]:
        response = self._logs.start_query(
            logGroupName=_LOG_GROUP_NAME,
            startTime=start_time,
            endTime=end_time,
            queryString=_SUSPICIOUS_QUERY,
        )
        results = self._poll_results(response["queryId"])

        return [
            fields["ip"]
            for row in results
            for fields in [dict((f["field"], f["value"]) for f in row)]
            if fields.get("ip")
        ]

    def _poll_results(self, query_id: str) -> list[Any]:
        deadline = time.time() + _QUERY_TIMEOUT_SECONDS
        while time.time() < deadline:
            response = self._logs.get_query_results(queryId=query_id)
            status = response["status"]
            if status == "Complete":
                return response.get("results", [])
            if status in ("Failed", "Cancelled"):
                return []
            time.sleep(_QUERY_POLL_INTERVAL)
        return []

    def _store(self, ips: list[str], alarm_name: str) -> None:
        pipe = self.redis_client.pipeline()
        for ip in ips:
            pipe.set(
                f"bot:blacklist:{ip}",
                json.dumps(
                    {"reason": "bot-detection", "alarm": alarm_name},
                    ensure_ascii=False,
                ),
                ex=self.blacklist_ttl_seconds,
            )
        pipe.execute()
