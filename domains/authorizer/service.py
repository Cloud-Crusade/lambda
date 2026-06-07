"""예약 토큰(RS256) + 인증 토큰(HS256) 을 함께 검증해 동일 유저인지로 인가.

흐름:
  1. Reservation 헤더의 예약 토큰을 S3 공개키로 RS256 검증
  2. Authorization 헤더의 인증 토큰을 Secrets Manager 대칭키로 HS256 검증
  3. 두 토큰의 user_id 가 동일하면 인가, 다르면 거부

오류 구분(진입점이 API Gateway 응답으로 매핑):
  - 자격 증명 누락(MissingCredentialError) → 401
  - 서명 무효 · 클레임 누락 · 유저 불일치(InvalidCredentialError) → 403
"""
import os
from typing import Any

import jwt

from common.logging import getLogger
from domains.authorizer.keys import KeyProvider

logger = getLogger("authorizer")

RESERVATION_HEADER = "reservation"
AUTHORIZATION_HEADER = "authorization"

RESERVATION_ALGORITHM = "RS256"
AUTHORIZATION_ALGORITHM = "HS256"
# 예약 토큰 aud — ticketing 이 발급 시 넣는 값과 일치해야 한다(QueueService.JWT_AUDIENCE)
RESERVATION_AUDIENCE = os.environ.get("RESERVATION_AUDIENCE", "reservation_waiting")
# 동일 유저 판별에 사용할 클레임 이름 (두 토큰 공통)
USER_CLAIM = os.environ.get("USER_CLAIM", "user_id")


class AuthorizationError(Exception):
    """인가 실패 베이스."""


class MissingCredentialError(AuthorizationError):
    """자격 증명(헤더) 누락 → 401."""


class InvalidCredentialError(AuthorizationError):
    """검증 실패(서명·클레임·유저 불일치) → 403."""


class AuthorizerService:
    def __init__(self, key_provider: KeyProvider | None = None) -> None:
        self._keys = key_provider or KeyProvider()

    def authorize(self, headers: dict[str, str]) -> str:
        """검증 통과 시 user_id 반환, 실패 시 AuthorizationError 하위 예외 발생."""
        reservation_token = self._extractToken(headers, RESERVATION_HEADER)
        authorization_token = self._extractToken(headers, AUTHORIZATION_HEADER)

        reservation_user = self._verifyReservation(reservation_token)
        authorization_user = self._verifyAuthorization(authorization_token)

        if reservation_user != authorization_user:
            # 어느 토큰의 유저인지 로그로만 남기고 응답 본문엔 노출하지 않음
            logger.info(
                "user_mismatch: reservation=%s authorization=%s",
                reservation_user, authorization_user,
            )
            raise InvalidCredentialError("reservation/authorization user mismatch")
        return reservation_user

    def _extractToken(self, headers: dict[str, str], name: str) -> str:
        value = headers.get(name, "")
        if not value:
            raise MissingCredentialError(f"missing {name} header")
        # "Bearer <token>" 형태도 허용 (Authorization 헤더 관례)
        parts = value.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
        return value

    def _verifyReservation(self, token: str) -> str:
        try:
            claims = jwt.decode(
                token,
                self._keys.reservationPublicKey(),
                algorithms=[RESERVATION_ALGORITHM],
                audience=RESERVATION_AUDIENCE,
            )
        except jwt.PyJWTError as error:
            raise InvalidCredentialError(f"reservation token invalid: {error}") from error
        return self._userId(claims, RESERVATION_HEADER)

    def _verifyAuthorization(self, token: str) -> str:
        try:
            claims = jwt.decode(
                token,
                self._keys.authorizationSecret(),
                algorithms=[AUTHORIZATION_ALGORITHM],
                # 인증 토큰의 aud 규약이 정해지면 audience 로 좁힌다(현재는 미검증)
                options={"verify_aud": False},
            )
        except jwt.PyJWTError as error:
            raise InvalidCredentialError(f"authorization token invalid: {error}") from error
        return self._userId(claims, AUTHORIZATION_HEADER)

    def _userId(self, claims: dict[str, Any], source: str) -> str:
        user_id = claims.get(USER_CLAIM)
        if not user_id:
            raise InvalidCredentialError(f"{source} token missing {USER_CLAIM} claim")
        return str(user_id)
