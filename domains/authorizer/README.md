# authorizer (lambda 도메인)

## 개요

API Gateway **REST REQUEST authorizer**. 예약 토큰(RS256)과 인증 토큰(HS256)을 함께 검증해 두 토큰의 `user_id` 가 같으면 Allow, 아니면 Deny 하는 IAM 정책 문서를 반환합니다. **non-VPC** 로 동작합니다(공개키를 CloudFront 로 fetch 하므로 S3 IAM·VPC 불필요).

## 트리거 · 핸들러

- **트리거**: API Gateway REST API 의 REQUEST authorizer(`identity=Reservation` 헤더 기준 캐시, 기본 TTL 300s).
- **핸들러**: `domains.authorizer.index.lambda_handler` → `AuthorizerService.authorize(headers)` 위임.

| 파일 | 책임 |
|------|------|
| `index.py` | 헤더 소문자 정규화, IAM 정책(`_policy`) 생성, 오류 → API Gateway 응답 매핑 |
| `service.py` | `AuthorizerService` — 헤더 추출·이중 토큰 검증·동일 유저 판별 |
| `keys.py` | `KeyProvider` — 예약 공개키(CloudFront fetch) + 인증 대칭키(Secrets Extension) |

## 핵심 동작

- **이중 토큰 검증** — `Reservation` 헤더의 예약 토큰을 RS256(`aud=RESERVATION_AUDIENCE`)으로, `Authorization` 헤더의 인증 토큰을 HS256(aud 미검증)으로 검증합니다. 알고리즘은 `algorithms=[...]` 로 고정해 alg confusion 을 차단합니다.
- **동일 유저 판별** — 예약 토큰은 `user_id` 클레임, 인증 토큰은 `sub` 클레임을 식별자로 쓰며, 두 값이 다르면 거부(불일치 사유는 로그만, 본문 비노출). `None`·빈 문자열만 누락 처리하고 `0` 같은 falsy 값은 유효 식별자로 허용합니다.
- **헤더 추출** — `Bearer ` 접두사 허용, 접두사 없는 단일 토큰도 허용, 공백 포함 비정상 포맷은 누락으로 간주합니다.
- **오류 → 응답 매핑** — 누락(`MissingCredentialError`)은 `raise Exception("Unauthorized")` 로 **401**, 검증 실패(`AuthorizationError`)는 **Deny(403)**, 그 외 예외(키 조회·설정 누락)는 **fail-closed Deny**(열려버리는 500 회피).
- **와일드카드 Resource** — Allow 정책의 Resource 를 `{apiId}/{stage}/*/*` 로 둡니다. authorizer Allow 는 헤더 기준으로 캐시되므로 특정 `methodArn` 으로 좁히면 다른 메서드가 403 이 됩니다. `context.user_id` 로 백엔드(`$context.authorizer.user_id`)에 전달합니다.
- **공개키 캐시** — `KeyProvider` 가 CloudFront URL 에서 최초 1회 fetch 후 인스턴스 캐시(회전이 드묾). 평문(http)은 MITM 키 변조 위험으로 **https 만 허용**합니다.

## 의존 (AWS 서비스 · env)

- **AWS**: API Gateway(REQUEST authorizer), CloudFront(예약 공개키), Secrets Manager + Parameters/Secrets Extension(인증 대칭키). non-VPC.
- **라이브러리**: `pyjwt[crypto]`(jwt-layer).

| 환경변수 | 설명 |
|----------|------|
| `PUBLIC_KEY_URL` | 예약 공개키 CloudFront URL (https 필수) |
| `AUTHORIZATION_SECRET_ARN` | 인증 대칭키 Secrets Manager ARN/이름 |
| `RESERVATION_AUDIENCE` | 예약 토큰 aud (기본 `reservation_waiting`) |
| `RESERVATION_USER_CLAIM` | 예약 토큰 식별자 클레임 (기본 `user_id`) |
| `AUTHORIZATION_USER_CLAIM` | 인증 토큰 식별자 클레임 (기본 `sub`) |

> 공통 시크릿 조회는 [../../common/README.md](../../common/README.md) 참고.

---
⬆ [domains README로](../README.md)
