# common · 공통 모듈

모든 도메인 Lambda 가 공유하는 횡단 관심사 모듈입니다. 배포 시 CI 가 각 `domains/<도메인>/` 에 **복사**해 함께 번들합니다(자기완결 패키징).

## ① 개요

| 파일 | 역할 |
|------|------|
| `logging.py` | 모든 Lambda 가 동일하게 쓰는 INFO 표준 로거 |
| `secrets.py` | Parameters/Secrets Lambda Extension 로컬 캐시 기반 시크릿 조회 |

## ② 설계 원칙 & 고려 사항

- **시크릿은 값이 아닌 이름/ARN 만 env 로** 둡니다. 실제 값은 런타임에 Secrets Extension 캐시에서 조회하므로, 키 회전이 **재배포 없이** 반영됩니다.
- **Extension 캐시 우선** — boto3 `GetSecretValue` 직접 호출 대비 호출 수·비용·지연을 줄입니다(로컬 `localhost:2773` 캐시). 코드 레벨 캐시는 두지 않고 Extension 캐시만 신뢰합니다.
- **명확한 실패** — Extension 레이어 미부착/로컬 실행이면 인증 토큰(`AWS_SESSION_TOKEN`)이 없으므로, 모호한 네트워크 오류 대신 `SecretsConfigError` 로 원인을 드러냅니다.
- **로거는 가볍게** — `getLogger` 는 레벨만 INFO 로 설정하고 핸들러는 추가하지 않습니다(Lambda 런타임 기본 핸들러 사용).

## ③ 구성

```
common/
├── logging.py     # getLogger(name="lambda") -> Logger
└── secrets.py     # get_secret_string(secret_id, *, timeout=5) -> str
```

| 심볼 | 책임 |
|------|------|
| `getLogger(name)` | 이름별 `logging.Logger` 반환, 레벨 INFO 고정 |
| `get_secret_string(secret_id, *, timeout)` | Extension 캐시 엔드포인트에서 `SecretString` 조회 |
| `SecretsConfigError` | Extension 조회에 필요한 설정(세션 토큰) 누락 시 발생 |

## ④ 핵심 로직 / 동작

### logging.py

`getLogger(name="lambda")` 는 해당 이름의 로거에 `INFO` 레벨을 설정해 반환합니다. 도메인별로 `getLogger("ticketing")`, `getLogger("authorizer")` 등 이름을 달리 부여해 CloudWatch 로그에서 도메인을 구분합니다.

### secrets.py — Secrets Extension 조회

```
get_secret_string(secret_id)
  1. AWS_SESSION_TOKEN 확인 → 없으면 SecretsConfigError (레이어 미부착/로컬)
  2. GET http://localhost:2773/secretsmanager/get?secretId=<url-encoded>
       헤더 X-Aws-Parameters-Secrets-Token: <session token>
  3. 응답 JSON 의 SecretString 반환
```

두 가지 회귀 방지 포인트가 코드에 녹아 있습니다.

- **세션 토큰 가드** — `AWS_SESSION_TOKEN` 부재 시 즉시 `SecretsConfigError`. 콜드스타트(Extension 미준비)·로컬 실행을 명확히 구분합니다.
- **`:` / `/` over-encoding 방지** — `urllib.parse.quote(secret_id, safe=':/')`. ARN(`arn:aws:...`)의 `:` 까지 인코딩하면 Extension 이 Secrets Manager 에 잘못된 id(`arn%3A…`)를 전달해 **400 Invalid name** 이 발생합니다. 이 회귀를 막기 위해 `:` 와 `/` 는 인코딩에서 제외합니다.

> Extension 준비 시점 문제로, 시크릿에 의존하는 서비스 객체는 INIT 가 아니라 **첫 invoke 때 lazy 생성**합니다(각 도메인 `index.py` 의 `_get_service()` 참고).

## ⑤ 환경변수 · 의존

| 변수 | 설명 | 기본 |
|------|------|------|
| `PARAMETERS_SECRETS_EXTENSION_HTTP_PORT` | Extension 캐시 포트 | `2773` |
| `AWS_SESSION_TOKEN` | Lambda 런타임이 자동 주입(Extension 인증 토큰) | — |

- **의존**: Python stdlib (`logging`, `json`, `os`, `urllib`) 전용 — 외부 패키지 없음.
- **런타임 전제**: Parameters and Secrets Lambda Extension(관리형 Layer) 부착.

---

⬆ [lambda 대표 README로](../README.md)
