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

    def test_options_v2_function_url(self):
        # Function URL(payload v2.0): 메서드가 requestContext.http.method 에 위치
        res = index_module.lambda_handler(
            {"requestContext": {"http": {"method": "OPTIONS"}}}, None
        )
        self.assertEqual(res["statusCode"], 204)


class EventIdExtractionTest(unittest.TestCase):
    def test_path_parameters_api_gw(self):
        # 기존 동작 유지: API GW REST path 변수
        self.assertEqual(
            index_module._event_id({"pathParameters": {"event_id": "E1"}}), "E1"
        )

    def test_query_string_function_url(self):
        # 추가: Function URL ?event_id=
        self.assertEqual(
            index_module._event_id({"queryStringParameters": {"event_id": "E2"}}), "E2"
        )

    def test_raw_path_function_url(self):
        # 추가: Function URL /queue/<id> (rawPath 마지막 세그먼트)
        self.assertEqual(index_module._event_id({"rawPath": "/queue/E3"}), "E3")

    def test_missing_returns_empty(self):
        # /queue 만(이벤트 없음) → 빈 값 → 핸들러가 400
        self.assertEqual(index_module._event_id({"rawPath": "/queue"}), "")
        self.assertEqual(index_module._event_id({}), "")


if __name__ == "__main__":
    unittest.main()
