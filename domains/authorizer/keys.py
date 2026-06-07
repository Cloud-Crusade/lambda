"""검증키 조달 — S3 의 Reservation 공개키(RS256), Secrets Manager 의 Authorization 대칭키(HS256).

- Reservation 공개키: S3 객체. 회전이 드물고 배포로 갱신되므로 인스턴스에 캐시한다.
- Authorization 대칭키: AWS Parameters and Secrets Lambda Extension(로컬 캐시 레이어)의
  localhost 엔드포인트로 조회한다. 캐시·TTL 갱신은 익스텐션이 담당하므로 코드에서
  별도 캐시하지 않는다(시크릿 회전이 재배포 없이 반영됨).
키 위치는 모두 infra(terraform)에서 환경변수로 주입한다.
"""
import json
import os
import urllib.parse
import urllib.request
from typing import Any

import boto3

from common.logging import getLogger

logger = getLogger("authorizer")

# Reservation 공개키 — S3 (infra: modules/lambda lambda_env.authorizer 주입)
PUBLIC_KEY_BUCKET = os.environ.get("PUBLIC_KEY_BUCKET", "")
PUBLIC_KEY_KEY = os.environ.get("PUBLIC_KEY_KEY", "")
# Authorization 대칭키 — Secrets Manager 시크릿 ARN(또는 이름)
AUTHORIZATION_SECRET_ARN = os.environ.get("AUTHORIZATION_SECRET_ARN", "")
# Secrets Extension 로컬 HTTP 포트 (레이어 기본값 2773)
SECRETS_EXTENSION_PORT = os.environ.get("PARAMETERS_SECRETS_EXTENSION_HTTP_PORT", "2773")
SECRETS_EXTENSION_TIMEOUT = 2


class KeyConfigError(RuntimeError):
    """검증키 조달에 필요한 환경변수/실행 환경 값이 누락됨 (설정 오류)."""


class KeyProvider:
    def __init__(self, s3_client: Any = None) -> None:
        self._s3 = s3_client or boto3.client("s3")
        self._public_key: str | None = None

    def reservationPublicKey(self) -> str:
        # 최초 1회만 S3 조회 → 이후 호출은 인스턴스 캐시 사용
        if self._public_key is None:
            # env 누락은 S3 오류 전에 명확히 드러낸다(운영/디버깅)
            if not PUBLIC_KEY_BUCKET or not PUBLIC_KEY_KEY:
                raise KeyConfigError("PUBLIC_KEY_BUCKET/PUBLIC_KEY_KEY 환경변수가 비어 있습니다")
            response = self._s3.get_object(Bucket=PUBLIC_KEY_BUCKET, Key=PUBLIC_KEY_KEY)
            self._public_key = response["Body"].read().decode("utf-8")
            logger.info(
                "reservation_public_key_loaded: s3://%s/%s",
                PUBLIC_KEY_BUCKET, PUBLIC_KEY_KEY,
            )
        return self._public_key

    def authorizationSecret(self) -> str:
        if not AUTHORIZATION_SECRET_ARN:
            raise KeyConfigError("AUTHORIZATION_SECRET_ARN 환경변수가 비어 있습니다")
        # 익스텐션 인증 토큰 — Lambda 실행 환경에 자동 주입되는 세션 토큰
        session_token = os.environ.get("AWS_SESSION_TOKEN")
        if not session_token:
            raise KeyConfigError("AWS_SESSION_TOKEN 이 없습니다 (Secrets Extension 레이어 미부착)")
        # Secrets Extension 익스텐션 캐시를 통해 조회(매 호출 localhost, 외부 API 아님)
        url = (
            f"http://localhost:{SECRETS_EXTENSION_PORT}/secretsmanager/get"
            f"?secretId={urllib.parse.quote(AUTHORIZATION_SECRET_ARN, safe='')}"
        )
        request = urllib.request.Request(url)
        request.add_header("X-Aws-Parameters-Secrets-Token", session_token)
        with urllib.request.urlopen(request, timeout=SECRETS_EXTENSION_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload["SecretString"]
