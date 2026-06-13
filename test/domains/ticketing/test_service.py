"""QueueService 의 입장 토큰 발급 단위 테스트 — 만료(exp) 클레임 포함을 검증.

redis·jwt 미설치 환경에서도 돌도록 import 전에 둘 다 스텁한다.
- redis: QueueService 가 register_script 만 호출(스크립트 실행은 테스트 대상 아님)
- jwt: encode 는 payload 를 그대로 보관(클레임 검증), algorithms.RSAAlgorithm 은 키 검증 통과용
실행: python -m unittest test/domains/ticketing/test_service.py
"""
import sys
import types
import unittest
from unittest import mock

# redis 스텁 — QueueService 는 주입된 client 만 사용(redis.Redis 미호출)
if "redis" not in sys.modules:
    sys.modules["redis"] = types.ModuleType("redis")

# jwt 스텁 — encode 는 (payload, key, algorithm) 을 기록하고 payload 를 반환.
# algorithms.RSAAlgorithm 은 _loadSigningKey 의 PEM 검증을 통과시키는 더미.
if "jwt" not in sys.modules:
    jwt_stub = types.ModuleType("jwt")
    _encode_calls: list[dict] = []

    def _encode(payload, key, algorithm=None):
        _encode_calls.append({"payload": payload, "key": key, "algorithm": algorithm})
        return "signed-token"

    jwt_stub.encode = _encode
    jwt_stub._encode_calls = _encode_calls

    algorithms_stub = types.ModuleType("jwt.algorithms")

    class _RSAAlgorithm:
        SHA256 = "sha256"

        def __init__(self, _hash):
            pass

        def prepare_key(self, secret):
            return secret

    algorithms_stub.RSAAlgorithm = _RSAAlgorithm
    jwt_stub.algorithms = algorithms_stub
    sys.modules["jwt"] = jwt_stub
    sys.modules["jwt.algorithms"] = algorithms_stub

import jwt  # noqa: E402

from domains.ticketing import service as service_module  # noqa: E402
from domains.ticketing.service import QueueService  # noqa: E402


def _service() -> QueueService:
    # register_script 는 호출만 통과시키면 됨(스크립트 실행 미사용)
    fake_redis = mock.MagicMock()
    return QueueService(redis_client=fake_redis, signing_key="DUMMY_PEM")


class CompletedTokenTest(unittest.TestCase):
    def setUp(self) -> None:
        jwt._encode_calls.clear()

    def test_completed_token_includes_bounded_exp(self):
        with mock.patch.object(service_module.time, "time", return_value=1_000):
            result = service_module.QueueService._completed(
                _service(), event_id="e1", user_id="u1",
            )

        self.assertEqual(result["code"], "COMPLETED")
        self.assertEqual(result["data"]["token"], "signed-token")

        payload = jwt._encode_calls[-1]["payload"]
        self.assertEqual(payload["user_id"], "u1")
        self.assertEqual(payload["event_id"], "e1")
        self.assertEqual(payload["aud"], service_module.JWT_AUDIENCE)
        self.assertEqual(payload["iat"], 1_000)
        # exp = iat + TTL → 입장 토큰이 시간 제한으로 만료됨
        self.assertEqual(payload["exp"], 1_000 + service_module.RESERVATION_TOKEN_TTL_SECONDS)

    def test_default_ttl_is_ten_minutes(self):
        self.assertEqual(service_module.RESERVATION_TOKEN_TTL_SECONDS, 600)


if __name__ == "__main__":
    unittest.main()
