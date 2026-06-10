"""CaptchaService(ALTCHA PoW) 발급·검증 단위 테스트.

실행: python -m unittest test/domains/captcha/test_service.py
"""
import base64
import hashlib
import json
import unittest

from domains.captcha.service import CaptchaConfigError, CaptchaService

SECRET = "test-secret"
COMPLEXITY = 500


def _solve(challenge: dict) -> str:
    # PoW — maxnumber 까지 해시 일치하는 number 를 찾아 토큰을 만든다
    number = next(
        n
        for n in range(challenge["maxnumber"] + 1)
        if hashlib.sha256(f"{challenge['salt']}{n}".encode()).hexdigest()
        == challenge["challenge"]
    )
    payload = {
        "algorithm": challenge["algorithm"],
        "challenge": challenge["challenge"],
        "number": number,
        "salt": challenge["salt"],
        "signature": challenge["signature"],
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


class CaptchaServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = CaptchaService(secret=SECRET, complexity=COMPLEXITY)

    def test_issue_and_verify_roundtrip(self) -> None:
        token = _solve(self.service.issueChallenge())
        self.assertTrue(self.service.verify(token))

    def test_verify_rejects_tampered_number(self) -> None:
        data = json.loads(base64.b64decode(_solve(self.service.issueChallenge())))
        data["number"] += 1
        tampered = base64.b64encode(json.dumps(data).encode()).decode()
        self.assertFalse(self.service.verify(tampered))

    def test_verify_rejects_wrong_secret(self) -> None:
        token = _solve(self.service.issueChallenge())
        other = CaptchaService(secret="other-secret", complexity=COMPLEXITY)
        self.assertFalse(other.verify(token))

    def test_verify_rejects_garbage(self) -> None:
        self.assertFalse(self.service.verify("not-a-valid-token"))

    def test_missing_secret_raises(self) -> None:
        with self.assertRaises(CaptchaConfigError):
            CaptchaService(secret="")


if __name__ == "__main__":
    unittest.main()
