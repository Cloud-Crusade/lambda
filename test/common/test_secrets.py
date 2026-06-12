"""common.secrets — Secrets 확장 캐시 조회 단위 테스트.

실행: python -m unittest test/common/test_secrets.py
"""
import json
import unittest
from unittest import mock

from common import secrets as secrets_module


class GetSecretStringTest(unittest.TestCase):
    @mock.patch.dict("os.environ", {"AWS_SESSION_TOKEN": "session-token"})
    @mock.patch("common.secrets.urllib.request.urlopen")
    def test_returns_secret_string(self, mock_urlopen: mock.MagicMock) -> None:
        response = mock.MagicMock()
        response.read.return_value = json.dumps({"SecretString": "s3cr3t"}).encode()
        mock_urlopen.return_value.__enter__.return_value = response

        result = secrets_module.get_secret_string("dev-captcha-hmac-secret")

        self.assertEqual(result, "s3cr3t")
        # 확장 엔드포인트 + 인증 토큰 헤더로 호출했는지 확인 (헤더명은 대소문자 무관 검사)
        request = mock_urlopen.call_args.args[0]
        self.assertIn("/secretsmanager/get", request.full_url)
        self.assertIn("secretId=dev-captcha-hmac-secret", request.full_url)
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["x-aws-parameters-secrets-token"], "session-token")
        # 기본 timeout(5s)이 urlopen 으로 전달되는지
        self.assertEqual(mock_urlopen.call_args.kwargs["timeout"], 5)

    @mock.patch.dict("os.environ", {"AWS_SESSION_TOKEN": "session-token"})
    @mock.patch("common.secrets.urllib.request.urlopen")
    def test_arn_secret_id_passed_raw(self, mock_urlopen: mock.MagicMock) -> None:
        # ARN 의 ':'/'/' 가 인코딩되면 확장이 SM 에 잘못된 id 를 넘겨 400 → raw 전달을 회귀 가드
        response = mock.MagicMock()
        response.read.return_value = json.dumps({"SecretString": "pem"}).encode()
        mock_urlopen.return_value.__enter__.return_value = response

        arn = "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:dev-reservation-private-key-AbCdEf"
        secrets_module.get_secret_string(arn)

        url = mock_urlopen.call_args.args[0].full_url
        self.assertNotIn("%3A", url)
        self.assertNotIn("%2F", url)
        self.assertIn(f"secretId={arn}", url)

    @mock.patch.dict("os.environ", {"AWS_SESSION_TOKEN": "session-token"})
    @mock.patch("common.secrets.urllib.request.urlopen")
    def test_passes_custom_timeout(self, mock_urlopen: mock.MagicMock) -> None:
        response = mock.MagicMock()
        response.read.return_value = json.dumps({"SecretString": "s"}).encode()
        mock_urlopen.return_value.__enter__.return_value = response

        secrets_module.get_secret_string("sid", timeout=2)

        self.assertEqual(mock_urlopen.call_args.kwargs["timeout"], 2)

    @mock.patch.dict("os.environ", {}, clear=True)
    def test_missing_session_token_raises(self) -> None:
        with self.assertRaises(secrets_module.SecretsConfigError):
            secrets_module.get_secret_string("dev-captcha-hmac-secret")


if __name__ == "__main__":
    unittest.main()
