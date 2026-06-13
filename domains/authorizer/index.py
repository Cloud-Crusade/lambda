"""authorizer 도메인 단일 진입점 — API Gateway REQUEST authorizer.

반환은 IAM 정책 문서(Allow/Deny). 자격 증명 누락 시에는 'Unauthorized' 예외를
던져 API Gateway 가 401 로 매핑하게 한다(서명 무효·유저 불일치는 Deny → 403).
"""
from typing import Any

from common.logging import getLogger
try:
    from .service import (  # 패키지 로드(repo·테스트)
        AuthorizationError,
        AuthorizerService,
        MissingCredentialError,
    )
except ImportError:
    from service import (  # 평면 zip(Lambda)
        AuthorizationError,
        AuthorizerService,
        MissingCredentialError,
    )

logger = getLogger("authorizer")

_service = AuthorizerService()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method_arn = event.get("methodArn", "*")
    headers = _normalizeHeaders(event)

    try:
        user_id = _service.authorize(headers)
    except MissingCredentialError as error:
        logger.info("unauthorized: %s", error)
        # API Gateway 는 정확히 'Unauthorized' 메시지를 401 로 매핑한다
        raise Exception("Unauthorized") from error
    except AuthorizationError as error:
        logger.info("forbidden: %s", error)
        return _policy(principal_id="unauthorized", effect="Deny", method_arn=method_arn)
    except Exception:
        # 키 조회 실패·설정 누락 등 예상치 못한 오류는 fail-closed 로 Deny (500 회피)
        logger.exception("authorizer_error")
        return _policy(principal_id="unauthorized", effect="Deny", method_arn=method_arn)

    logger.info("authorized: user_id=%s", user_id)
    # Allow 는 캐시(identity=Reservation 헤더, 기본 TTL 300s)되므로 정책 Resource 를 메서드/경로
    # 와일드카드로 둔다. 특정 methodArn 이면 첫 요청(예 GET) 정책이 캐시돼 다른 메서드(DELETE)가 403.
    return _policy(
        principal_id=user_id, effect="Allow", method_arn=_wildcardResource(method_arn), user_id=user_id,
    )


def _wildcardResource(method_arn: str) -> str:
    # arn:aws:execute-api:region:acct:apiId/stage/METHOD/path → .../apiId/stage/* (메서드·경로 무관)
    parts = method_arn.split(":", 5)
    if len(parts) < 6:
        return method_arn
    segments = parts[5].split("/")
    if len(segments) < 2:
        return method_arn
    parts[5] = f"{segments[0]}/{segments[1]}/*"
    return ":".join(parts)


def _normalizeHeaders(event: dict[str, Any]) -> dict[str, str]:
    # REST API REQUEST authorizer 는 헤더를 원래 케이스로 전달 → 소문자로 정규화
    raw = event.get("headers") or {}
    return {key.lower(): value for key, value in raw.items()}


def _policy(
    *, principal_id: str, effect: str, method_arn: str, user_id: str | None = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": method_arn,
                },
            ],
        },
    }
    if user_id is not None:
        # 백엔드에서 $context.authorizer.user_id 로 사용 가능
        response["context"] = {"user_id": user_id}
    return response
