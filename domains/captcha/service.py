"""캡차(ALTCHA PoW) 챌린지 발급·검증 로직 — 외부 의존 없이 stdlib 로 구현.

흐름: 서버가 challenge(salt + 서버만 아는 number 의 해시 + HMAC 서명) 발급 →
클라이언트가 PoW 로 number 를 brute-force(해시 일치) → 서버가 해시·HMAC 서명·만료를 검증.
검증은 전부 로컬 계산이며 외부 호출이 없다. app(WAS) 검증측과 동일 HMAC 시크릿을 공유한다.
"""
import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

from common.logging import getLogger

logger = getLogger("captcha")

ALGORITHM = "SHA-256"
CHALLENGE_TTL_SECONDS = 300


class CaptchaConfigError(RuntimeError):
    """CAPTCHA_HMAC_SECRET 미설정 (설정 오류)."""


class CaptchaService:
    def __init__(self, secret: str | None = None, complexity: int | None = None) -> None:
        secret = secret if secret is not None else os.environ.get("CAPTCHA_HMAC_SECRET", "")
        if not secret:
            raise CaptchaConfigError("CAPTCHA_HMAC_SECRET 이 비어 있습니다 — HMAC 키가 필요합니다")
        self._secret = secret.encode()
        # 0 이하면 randbelow 가 ValueError → 최소 1 로 보정
        raw = complexity if complexity is not None else int(os.environ.get("CAPTCHA_COMPLEXITY", 100_000))
        self._complexity = max(1, raw)

    def _sha256Hex(self, value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def _sign(self, challenge: str) -> str:
        return hmac.new(self._secret, challenge.encode(), hashlib.sha256).hexdigest()

    def issueChallenge(self) -> dict[str, Any]:
        # number 는 PoW 정답 — 클라이언트가 0..maxnumber(포함) 에서 brute-force 로 찾는다
        number = secrets.randbelow(self._complexity + 1)
        expires = int(time.time()) + CHALLENGE_TTL_SECONDS
        salt = f"{secrets.token_hex(12)}.{expires}"
        challenge = self._sha256Hex(salt + str(number))
        return {
            "algorithm": ALGORITHM,
            "challenge": challenge,
            "maxnumber": self._complexity,
            "salt": salt,
            "signature": self._sign(challenge),
        }

    def verify(self, token: str) -> bool:
        try:
            # 패딩 보정 + validate=True 로 엄격 디코딩(알파벳 외 문자/변형 거부)
            padded = token + "=" * (-len(token) % 4)
            data: Any = json.loads(base64.b64decode(padded, validate=True))
        except (ValueError, binascii.Error):
            return False
        if not isinstance(data, dict) or data.get("algorithm") != ALGORITHM:
            return False

        salt = data.get("salt")
        number = data.get("number")
        challenge = data.get("challenge")
        signature = data.get("signature")
        if not isinstance(salt, str) or not isinstance(number, int):
            return False
        if not isinstance(challenge, str) or not isinstance(signature, str):
            return False

        try:
            expires = int(salt.rsplit(".", 1)[1])
        except (IndexError, ValueError):
            return False
        if time.time() > expires:
            return False

        if not hmac.compare_digest(self._sha256Hex(salt + str(number)), challenge):
            return False
        return hmac.compare_digest(self._sign(challenge), signature)
