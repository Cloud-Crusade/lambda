"""captcha 핸들러 — lazy 시크릿 조회 + CORS/OPTIONS 단위 테스트.

import 가 크래시 없이 되는 것 자체가 lazy 회귀 가드(eager 조회면 INIT 에서 실패).
실행: python -m unittest test/domains/captcha/test_index.py
"""
import json
import unittest
from unittest import mock

from domains.captcha import index as index_module


class CaptchaHandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        index_module._service = None

    def test_options_returns_204_with_cors(self):
        res = index_module.lambda_handler({"httpMethod": "OPTIONS"}, None)
        self.assertEqual(res["statusCode"], 204)
        self.assertIn("Reservation", res["headers"]["Access-Control-Allow-Headers"])

    def test_get_issues_challenge_with_cors(self):
        fake = mock.MagicMock()
        fake.issue_challenge.return_value = {"algorithm": "SHA-256", "challenge": "x"}
        with mock.patch.object(index_module, "_CAPTCHA_SECRET_ID", "sid"), \
                mock.patch.object(index_module, "get_secret_string", return_value="secret"), \
                mock.patch.object(index_module, "CaptchaService", return_value=fake):
            res = index_module.lambda_handler({"httpMethod": "GET"}, None)

        self.assertEqual(res["statusCode"], 200)
        self.assertEqual(res["headers"]["Access-Control-Allow-Origin"], "*")
        self.assertEqual(json.loads(res["body"])["algorithm"], "SHA-256")


if __name__ == "__main__":
    unittest.main()
