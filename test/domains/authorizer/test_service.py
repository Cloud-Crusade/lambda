"""AuthorizerService 의 인가 로직(헤더 추출·이중 검증·동일 유저 판별) 단위 테스트.

AWS SDK(boto3)·PyJWT 미설치 환경에서도 돌도록 import 전에 둘 다 스텁한다.
- boto3: KeyProvider 생성만 가능하면 됨(테스트는 FakeKeyProvider 주입)
- jwt: token(JSON 문자열)을 그대로 디코드하는 가짜 — 알고리즘 핀·키 사용처를 검증한다
실행: python -m unittest test/domains/authorizer/test_service.py
"""
import json
import sys
import types
import unittest

# boto3 스텁 — keys.py 의 boto3.client 호출만 통과시키면 됨
if "boto3" not in sys.modules:
    boto3_stub = types.ModuleType("boto3")
    boto3_stub.client = lambda *a, **k: None
    sys.modules["boto3"] = boto3_stub

# jwt 스텁 — token 은 compact JSON. {"_raise": true} 면 검증 실패를 모사한다.
if "jwt" not in sys.modules:
    jwt_stub = types.ModuleType("jwt")

    class _PyJWTError(Exception):
        pass

    _calls: list[dict] = []

    def _decode(token, key, algorithms=None, audience=None, options=None):
        _calls.append({"key": key, "algorithms": algorithms, "audience": audience})
        payload = json.loads(token)
        if payload.get("_raise"):
            raise _PyJWTError("invalid signature")
        return payload["claims"]

    jwt_stub.PyJWTError = _PyJWTError
    jwt_stub.decode = _decode
    jwt_stub._calls = _calls  # 테스트에서 핀 검증용으로 참조
    sys.modules["jwt"] = jwt_stub

import jwt  # noqa: E402

from domains.authorizer.service import (  # noqa: E402
    AuthorizerService,
    InvalidCredentialError,
    MissingCredentialError,
)


class _FakeKeyProvider:
    def reservationPublicKey(self) -> str:
        return "RESERVATION_PUBLIC_KEY"

    def authorizationSecret(self) -> str:
        return "AUTHORIZATION_SECRET"


def _token(user_id: str | None = "u1", *, raise_: bool = False) -> str:
    claims = {} if user_id is None else {"user_id": user_id}
    # compact(공백 없음) → "Bearer " 미사용 시 split 영향 없음
    return json.dumps({"claims": claims, "_raise": raise_}, separators=(",", ":"))


def _service() -> AuthorizerService:
    return AuthorizerService(key_provider=_FakeKeyProvider())


class AuthorizerServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        jwt._calls.clear()

    def test_same_user_authorized_returns_user_id(self):
        headers = {"reservation": _token("u1"), "authorization": _token("u1")}

        user_id = _service().authorize(headers)

        self.assertEqual(user_id, "u1")

    def test_pins_algorithms_and_keys_per_token(self):
        headers = {"reservation": _token("u1"), "authorization": _token("u1")}

        _service().authorize(headers)

        reservation_call, authorization_call = jwt._calls
        self.assertEqual(reservation_call["algorithms"], ["RS256"])
        self.assertEqual(reservation_call["key"], "RESERVATION_PUBLIC_KEY")
        self.assertEqual(authorization_call["algorithms"], ["HS256"])
        self.assertEqual(authorization_call["key"], "AUTHORIZATION_SECRET")

    def test_user_mismatch_rejected(self):
        headers = {"reservation": _token("u1"), "authorization": _token("u2")}

        with self.assertRaises(InvalidCredentialError):
            _service().authorize(headers)

    def test_missing_authorization_header_raises_missing(self):
        headers = {"reservation": _token("u1")}

        with self.assertRaises(MissingCredentialError):
            _service().authorize(headers)

    def test_missing_reservation_header_raises_missing(self):
        headers = {"authorization": _token("u1")}

        with self.assertRaises(MissingCredentialError):
            _service().authorize(headers)

    def test_invalid_signature_rejected(self):
        headers = {
            "reservation": _token("u1", raise_=True),
            "authorization": _token("u1"),
        }

        with self.assertRaises(InvalidCredentialError):
            _service().authorize(headers)

    def test_missing_user_claim_rejected(self):
        headers = {"reservation": _token(None), "authorization": _token("u1")}

        with self.assertRaises(InvalidCredentialError):
            _service().authorize(headers)

    def test_bearer_prefix_stripped(self):
        headers = {
            "reservation": _token("u1"),
            "authorization": f"Bearer {_token('u1')}",
        }

        self.assertEqual(_service().authorize(headers), "u1")


if __name__ == "__main__":
    unittest.main()
