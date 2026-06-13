"""KeyProvider 의 Reservation 공개키 fetch(CloudFront URL) 단위 테스트.

실행: python -m unittest test/domains/authorizer/test_keys.py
"""
import unittest
from unittest import mock

from domains.authorizer import keys as keys_module
from domains.authorizer.keys import KeyConfigError, KeyProvider


class ReservationPublicKeyTest(unittest.TestCase):
    def test_fetches_from_url_and_caches(self):
        response = mock.MagicMock()
        response.read.return_value = b"-----BEGIN PUBLIC KEY-----\nx\n-----END PUBLIC KEY-----\n"
        cm = mock.MagicMock()
        cm.__enter__.return_value = response

        with mock.patch.object(keys_module, "PUBLIC_KEY_URL", "https://cdn/pk.pem"), \
                mock.patch.object(keys_module.urllib.request, "urlopen", return_value=cm) as urlopen:
            provider = KeyProvider()
            self.assertIn("BEGIN PUBLIC KEY", provider.reservationPublicKey())
            provider.reservationPublicKey()  # 두 번째 호출은 인스턴스 캐시 → fetch 1회
            urlopen.assert_called_once()
            self.assertEqual(urlopen.call_args.args[0], "https://cdn/pk.pem")

    def test_missing_url_raises_config_error(self):
        with mock.patch.object(keys_module, "PUBLIC_KEY_URL", ""):
            with self.assertRaises(KeyConfigError):
                KeyProvider().reservationPublicKey()

    def test_non_https_url_raises_config_error(self):
        # 평문(http) fetch 는 키 변조 위험 → 거부
        with mock.patch.object(keys_module, "PUBLIC_KEY_URL", "http://cdn/pk.pem"):
            with self.assertRaises(KeyConfigError):
                KeyProvider().reservationPublicKey()


if __name__ == "__main__":
    unittest.main()
