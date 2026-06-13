"""검증키 조달 — CloudFront 의 Reservation 공개키(RS256), Secrets Manager 의 Authorization 대칭키(HS256).

- Reservation 공개키: CloudFront URL 로 fetch(non-VPC authorizer → S3 IAM 불필요). 회전이 드물어 인스턴스에 캐시.
- Authorization 대칭키: Parameters and Secrets Lambda Extension 의 localhost 캐시로 조회(회전이 재배포 없이 반영).
키 위치는 모두 infra(terraform)에서 환경변수로 주입한다.
"""
import os
import urllib.request

from common.logging import getLogger
from common.secrets import get_secret_string

logger = getLogger("authorizer")

# Reservation 공개키 — CloudFront URL (infra: lambda_env.authorizer 주입)
PUBLIC_KEY_URL = os.environ.get("PUBLIC_KEY_URL", "")
PUBLIC_KEY_FETCH_TIMEOUT = 3
# Authorization 대칭키 — Secrets Manager 시크릿 ARN(또는 이름)
AUTHORIZATION_SECRET_ARN = os.environ.get("AUTHORIZATION_SECRET_ARN", "")
# 익스텐션 조회 타임아웃(초) — authorizer 는 인증 경로라 짧게
SECRETS_EXTENSION_TIMEOUT = 2


class KeyConfigError(RuntimeError):
    """검증키 조달에 필요한 환경변수/실행 환경 값이 누락됨 (설정 오류)."""


class KeyProvider:
    def __init__(self) -> None:
        self._public_key: str | None = None

    def reservationPublicKey(self) -> str:
        # 최초 1회만 fetch → 이후 호출은 인스턴스 캐시 사용
        if self._public_key is None:
            if not PUBLIC_KEY_URL:
                raise KeyConfigError("PUBLIC_KEY_URL 환경변수가 비어 있습니다")
            with urllib.request.urlopen(  # noqa: S310
                PUBLIC_KEY_URL, timeout=PUBLIC_KEY_FETCH_TIMEOUT,
            ) as response:
                self._public_key = response.read().decode("utf-8")
            logger.info("reservation_public_key_loaded: %s", PUBLIC_KEY_URL)
        return self._public_key

    def authorizationSecret(self) -> str:
        if not AUTHORIZATION_SECRET_ARN:
            raise KeyConfigError("AUTHORIZATION_SECRET_ARN 환경변수가 비어 있습니다")
        return get_secret_string(AUTHORIZATION_SECRET_ARN, timeout=SECRETS_EXTENSION_TIMEOUT)
