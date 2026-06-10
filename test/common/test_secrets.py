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
        # 확장 엔드포인트 + 인증 토큰 헤더로 호출했는지 확인
        request = mock_urlopen.call_args.args[0]
        self.assertIn("/secretsmanager/get", request.full_url)
        self.assertIn("secretId=dev-captcha-hmac-secret", request.full_url)
        self.assertEqual(
            request.get_header("X-aws-parameters-secrets-token"), "session-token"
        )


if __name__ == "__main__":
    unittest.main()
