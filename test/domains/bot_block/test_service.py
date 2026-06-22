"""BotBlockService._parse_alarm 파싱 단위 테스트.

boto3 · redis 미설치 환경에서도 돌도록 import 전에 스텁을 주입한다.
실행: python -m unittest test/domains/bot_block/test_service.py
"""
import sys
import types
import unittest
from datetime import datetime, timezone
from unittest import mock

# redis 스텁
redis_stub = sys.modules.setdefault("redis", types.ModuleType("redis"))
if not hasattr(redis_stub, "RedisError"):

    class _RedisError(Exception):
        pass

    redis_stub.RedisError = _RedisError
    redis_stub.Redis = mock.MagicMock

# boto3 스텁 — client() 만 가짜로 반환
boto3_stub = sys.modules.setdefault("boto3", types.ModuleType("boto3"))
if not hasattr(boto3_stub, "client"):
    boto3_stub.client = mock.MagicMock(return_value=mock.MagicMock())

from domains.bot_block.service import BotBlockService  # noqa: E402


def _service() -> BotBlockService:
    svc = object.__new__(BotBlockService)
    svc.redis_client = mock.MagicMock()
    svc._logs = mock.MagicMock()
    svc.blacklist_ttl_seconds = 3600
    return svc


class ParseAlarmTest(unittest.TestCase):
    def test_parses_alarm_name_and_timestamp(self):
        event = {
            "detail": {
                "alarmName": "high-429-alarm",
                "state": {"timestamp": "2026-06-21T10:00:00Z"},
            }
        }

        alarm_name, alarm_time = _service()._parse_alarm(event)

        self.assertEqual(alarm_name, "high-429-alarm")
        self.assertEqual(alarm_time, datetime(2026, 6, 21, 10, 0, 0, tzinfo=timezone.utc))

    def test_empty_timestamp_falls_back_to_utc_now(self):
        event = {
            "detail": {
                "alarmName": "some-alarm",
                "state": {"timestamp": ""},
            }
        }

        before = datetime.now(timezone.utc)
        _, alarm_time = _service()._parse_alarm(event)
        after = datetime.now(timezone.utc)

        self.assertIsNotNone(alarm_time.tzinfo)
        self.assertGreaterEqual(alarm_time, before)
        self.assertLessEqual(alarm_time, after)

    def test_missing_timestamp_key_falls_back_to_utc_now(self):
        event = {"detail": {"alarmName": "no-ts-alarm", "state": {}}}

        before = datetime.now(timezone.utc)
        alarm_name, alarm_time = _service()._parse_alarm(event)
        after = datetime.now(timezone.utc)

        self.assertEqual(alarm_name, "no-ts-alarm")
        self.assertGreaterEqual(alarm_time, before)
        self.assertLessEqual(alarm_time, after)


if __name__ == "__main__":
    unittest.main()
