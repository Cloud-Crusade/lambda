"""QueueService 입장 토큰 발급 단위 테스트 — 만료(exp) 포함을 검증.

실행: python -m unittest test/domains/ticketing/test_service.py
"""
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("redis", types.ModuleType("redis"))

# 다른 테스트(authorizer)가 먼저 설치한 jwt 스텁과 공존하도록 심볼만 가산식으로 보강(import 순서 무관)
jwt_stub = sys.modules.setdefault("jwt", types.ModuleType("jwt"))
if not hasattr(jwt_stub, "_encode_calls"):
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
    sys.modules["jwt.algorithms"] = algorithms_stub

import jwt  # noqa: E402

from domains.ticketing import service as service_module  # noqa: E402
from domains.ticketing.service import QueueService  # noqa: E402


def _service() -> QueueService:
    return QueueService(redis_client=mock.MagicMock(), signing_key="DUMMY_PEM")


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
        self.assertEqual(payload["exp"], 1_000 + service_module.RESERVATION_TOKEN_TTL_SECONDS)

    def test_default_ttl_is_ten_minutes(self):
        self.assertEqual(service_module.RESERVATION_TOKEN_TTL_SECONDS, 600)


if __name__ == "__main__":
    unittest.main()
