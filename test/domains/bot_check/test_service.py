"""BotCheckService._track_and_block 및 Redis 장애 시 fail-open 동작 단위 테스트.

redis 미설치 환경에서도 돌도록 import 전에 redis 를 스텁한다.
실행: python -m unittest test/domains/bot_check/test_service.py
"""
import sys
import types
import unittest
from unittest import mock

# redis 스텁 — RedisError 와 Redis 클래스만 노출
redis_stub = sys.modules.setdefault("redis", types.ModuleType("redis"))
if not hasattr(redis_stub, "RedisError"):

    class _RedisError(Exception):
        pass

    redis_stub.RedisError = _RedisError
    redis_stub.Redis = mock.MagicMock

from domains.bot_check.service import BotCheckService, _COUNT_THRESHOLD  # noqa: E402

_METHOD_ARN = "arn:aws:execute-api:ap-northeast-2:123:api/prod/POST/payments"


def _event(ip: str = "1.2.3.4", path: str = "/payments") -> dict:
    return {
        "requestContext": {"identity": {"sourceIp": ip}},
        "path": path,
        "methodArn": _METHOD_ARN,
    }


def _service(redis_client: mock.MagicMock) -> BotCheckService:
    svc = object.__new__(BotCheckService)
    svc.redis_client = redis_client
    return svc


class TrackAndBlockTest(unittest.TestCase):
    def _make_pipe(self, count: int) -> mock.MagicMock:
        pipe = mock.MagicMock()
        pipe.execute.return_value = [count, True]
        return pipe

    def test_below_threshold_returns_false(self):
        redis_client = mock.MagicMock()
        redis_client.pipeline.return_value = self._make_pipe(_COUNT_THRESHOLD)

        result = _service(redis_client)._track_and_block("1.2.3.4")

        self.assertFalse(result)
        redis_client.set.assert_not_called()

    def test_above_threshold_sets_blacklist_and_returns_true(self):
        redis_client = mock.MagicMock()
        redis_client.pipeline.return_value = self._make_pipe(_COUNT_THRESHOLD + 1)

        result = _service(redis_client)._track_and_block("1.2.3.4")

        self.assertTrue(result)
        redis_client.set.assert_called_once()
        call_args = redis_client.set.call_args
        self.assertIn("bot:blacklist:1.2.3.4", call_args[0])

    def test_redis_error_in_check_returns_allow_policy(self):
        redis_client = mock.MagicMock()
        redis_client.pipeline.side_effect = redis_stub.RedisError("connection refused")

        svc = _service(redis_client)
        result = svc.check(_event())

        stmt = result["policyDocument"]["Statement"][0]
        self.assertEqual(stmt["Effect"], "Allow")


if __name__ == "__main__":
    unittest.main()
