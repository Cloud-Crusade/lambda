"""ticketing 핸들러 CORS 단위 테스트 — OPTIONS 프리플라이트가 Reservation 헤더를 허용하는지.

실행: python -m unittest test/domains/ticketing/test_index.py
"""
import sys
import types
import unittest

sys.modules.setdefault("redis", types.ModuleType("redis"))
# 다른 테스트 스텁과 공존하도록 jwt 모듈만 보장(index 가 import 함)
sys.modules.setdefault("jwt", types.ModuleType("jwt"))

from domains.ticketing import index as index_module  # noqa: E402


class QueueCorsTest(unittest.TestCase):
    def test_allow_headers_includes_reservation(self):
        # 입장 후 클라가 /queue 요청에도 Reservation 헤더를 실어 보냄 → 프리플라이트 허용돼야 함
        allow = index_module._CORS_HEADERS["Access-Control-Allow-Headers"]
        self.assertIn("Reservation", allow)
        self.assertIn("Authorization", allow)

    def test_options_returns_204_with_cors(self):
        res = index_module.lambda_handler({"httpMethod": "OPTIONS"}, None)
        self.assertEqual(res["statusCode"], 204)
        self.assertIn("Reservation", res["headers"]["Access-Control-Allow-Headers"])


if __name__ == "__main__":
    unittest.main()
