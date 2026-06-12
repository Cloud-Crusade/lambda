"""Secrets Manager 조회 — Lambda 'Parameters and Secrets Extension' 로컬 캐시 사용.

확장이 localhost:2773 에 띄우는 캐시 엔드포인트로 조회한다. GetSecretValue 직접 호출(boto3)
대비 호출 수·비용·지연을 줄이며(캐시), env 에는 시크릿 값이 아닌 이름/ARN 만 둔다.
"""
import json
import os
import urllib.parse
import urllib.request

_EXTENSION_PORT = os.environ.get("PARAMETERS_SECRETS_EXTENSION_HTTP_PORT", "2773")


class SecretsConfigError(RuntimeError):
    """Secrets 확장 조회에 필요한 설정(세션 토큰 등) 누락 (설정 오류)."""


def get_secret_string(secret_id: str, *, timeout: float = 5) -> str:
    # 확장 호출 인증 토큰 — 없으면 레이어 미부착/로컬 실행 → 원인을 명확히
    session_token = os.environ.get("AWS_SESSION_TOKEN")
    if not session_token:
        raise SecretsConfigError(
            "AWS_SESSION_TOKEN 이 없습니다 (Secrets Extension 레이어 미부착/로컬 실행)"
        )

    # ':'·'/' 는 쿼리에서 유효 → 인코딩하면 확장이 SM 에 잘못된 id(arn%3A…) 전달 → 400(Invalid name)
    url = (
        f"http://localhost:{_EXTENSION_PORT}/secretsmanager/get"
        f"?secretId={urllib.parse.quote(secret_id, safe=':/')}"
    )
    request = urllib.request.Request(url)
    request.add_header("X-Aws-Parameters-Secrets-Token", session_token)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = json.loads(response.read())
    return payload["SecretString"]
