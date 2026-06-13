"""AuthorizerService 의 인가 로직(헤더 추출·이중 검증·동일 유저 판별) 단위 테스트.

PyJWT 미설치 환경에서도 돌도록 import 전에 jwt 를 스텁한다(FakeKeyProvider 주입이라 키 의존 없음).
실행: python -m unittest test/domains/authorizer/test_service.py
"""
import json
import sys
import types
import unittest

# jwt 스텁 — token 은 compact JSON. {"_raise": true} 면 검증 실패를 모사한다.
# 다른 테스트(ticketing) 스텁과 공존하도록 심볼만 가산식으로 보강(import 순서 무관)
jwt_stub = sys.modules.setdefault("jwt", types.ModuleType("jwt"))
if not hasattr(jwt_stub, "_calls"):

    class _PyJWTError(Exception):
        pass

    _calls: list[dict] = []

    def _decode(token, key, algorithms=None, audience=None, options=None):
        _calls.append({
            "key": key, "algorithms": algorithms,
            "audience": audience, "options": options,
        })
        payload = json.loads(token)
        if payload.get("_raise"):
            raise _PyJWTError("invalid signature")
        return payload["claims"]

    jwt_stub.PyJWTError = _PyJWTError
    jwt_stub.decode = _decode
    jwt_stub._calls = _calls  # 테스트에서 핀 검증용으로 참조

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


def _resv_token(user_id: str | None = "u1", *, raise_: bool = False) -> str:
    # 예약 토큰은 user id 를 user_id 클레임에, 인증 토큰은 sub 에 담는다(compact = "Bearer" 미사용)
    claims = {} if user_id is None else {"user_id": user_id}
    return json.dumps({"claims": claims, "_raise": raise_}, separators=(",", ":"))


def _auth_token(user_id: str | None = "u1", *, raise_: bool = False) -> str:
    claims = {} if user_id is None else {"sub": user_id}
    return json.dumps({"claims": claims, "_raise": raise_}, separators=(",", ":"))


def _service() -> AuthorizerService:
    return AuthorizerService(key_provider=_FakeKeyProvider())


class AuthorizerServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        jwt._calls.clear()

    def test_same_user_authorized_returns_user_id(self):
        headers = {"reservation": _resv_token("u1"), "authorization": _auth_token("u1")}

        user_id = _service().authorize(headers)

        self.assertEqual(user_id, "u1")

    def test_pins_algorithms_and_keys_per_token(self):
        headers = {"reservation": _resv_token("u1"), "authorization": _auth_token("u1")}

        _service().authorize(headers)

        reservation_call, authorization_call = jwt._calls
        self.assertEqual(reservation_call["algorithms"], ["RS256"])
        self.assertEqual(reservation_call["key"], "RESERVATION_PUBLIC_KEY")
        self.assertEqual(authorization_call["algorithms"], ["HS256"])
        self.assertEqual(authorization_call["key"], "AUTHORIZATION_SECRET")

    def test_pins_audience_and_aud_option(self):
        headers = {"reservation": _resv_token("u1"), "authorization": _auth_token("u1")}

        _service().authorize(headers)

        reservation_call, authorization_call = jwt._calls
        # 예약 토큰은 aud 핀 고정, 인증 토큰은 aud 미검증(규약 미정)
        self.assertEqual(reservation_call["audience"], "reservation_waiting")
        self.assertEqual(authorization_call["options"], {"verify_aud": False})

    def test_user_mismatch_rejected(self):
        headers = {"reservation": _resv_token("u1"), "authorization": _auth_token("u2")}

        with self.assertRaises(InvalidCredentialError):
            _service().authorize(headers)

    def test_missing_authorization_header_raises_missing(self):
        headers = {"reservation": _resv_token("u1")}

        with self.assertRaises(MissingCredentialError):
            _service().authorize(headers)

    def test_missing_reservation_header_raises_missing(self):
        headers = {"authorization": _auth_token("u1")}

        with self.assertRaises(MissingCredentialError):
            _service().authorize(headers)

    def test_invalid_signature_rejected(self):
        headers = {
            "reservation": _resv_token("u1", raise_=True),
            "authorization": _auth_token("u1"),
        }

        with self.assertRaises(InvalidCredentialError):
            _service().authorize(headers)

    def test_missing_user_claim_rejected(self):
        headers = {"reservation": _resv_token(None), "authorization": _auth_token("u1")}

        with self.assertRaises(InvalidCredentialError):
            _service().authorize(headers)

    def test_bearer_prefix_stripped(self):
        headers = {
            "reservation": _resv_token("u1"),
            "authorization": f"Bearer {_auth_token('u1')}",
        }

        self.assertEqual(_service().authorize(headers), "u1")

    def test_bearer_without_token_treated_as_missing(self):
        # 접두사만 오면 자격 증명 누락(401) 으로 매핑되어야 함
        headers = {"reservation": _resv_token("u1"), "authorization": "Bearer"}

        with self.assertRaises(MissingCredentialError):
            _service().authorize(headers)


if __name__ == "__main__":
    unittest.main()
