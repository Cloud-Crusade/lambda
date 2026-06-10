"""Secrets Manager 조회 — Lambda 'Parameters and Secrets Extension' 로컬 캐시 사용.

확장이 localhost:2773 에 띄우는 캐시 엔드포인트로 조회한다. GetSecretValue 직접 호출(boto3)
대비 호출 수·비용·지연을 줄이며(캐시), env 에는 시크릿 값이 아닌 이름/ARN 만 둔다.
"""
import json
import os
import urllib.parse
import urllib.request

_EXTENSION_PORT = os.environ.get("PARAMETERS_SECRETS_EXTENSION_HTTP_PORT", "2773")


def get_secret_string(secret_id: str) -> str:
    url = (
        f"http://localhost:{_EXTENSION_PORT}/secretsmanager/get"
        f"?secretId={urllib.parse.quote(secret_id, safe='')}"
    )
    request = urllib.request.Request(url)
    # 확장 호출 인증 — Lambda 실행 환경의 세션 토큰
    request.add_header("X-Aws-Parameters-Secrets-Token", os.environ["AWS_SESSION_TOKEN"])
    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
        payload = json.loads(response.read())
    return payload["SecretString"]
