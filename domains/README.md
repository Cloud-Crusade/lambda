# domains · 도메인 레이어

DDD 기반으로 도메인별 자기완결 모듈을 모은 디렉토리입니다. 각 도메인은 **단일 진입점**(`index.lambda_handler`)을 갖고, 로직은 OOP 파일로 분리합니다.

## ① 개요

| 도메인 | 한 줄 책임 | 트리거 | VPC | 세부 |
|--------|-----------|--------|-----|------|
| [ticketing](#ticketing) | 대기열 순번·입장 토큰(RS256) 발급 | API Gateway (GET `/queue/{event_id}`) | VPC | [README](./ticketing/README.md) |
| [authorizer](#authorizer) | 예약+인증 토큰 동시 검증 → IAM 정책 | API Gateway REQUEST authorizer | non-VPC | [README](./authorizer/README.md) |
| [persistence](#persistence) | SQS FIFO → RDS#2 멱등 적재(leaky bucket) | SQS FIFO 이벤트 소스 매핑 | VPC | [README](./persistence/README.md) |
| [captcha](#captcha) | ALTCHA PoW 챌린지 발급(공개 경로) | API Gateway (GET, AWS_PROXY) | non-VPC | [README](./captcha/README.md) |

> 각 도메인 상세는 도메인별 README 로 위임합니다: [ticketing](./ticketing/README.md) · [authorizer](./authorizer/README.md) · [persistence](./persistence/README.md) · [captcha](./captcha/README.md). 아래 섹션은 요약입니다.

## ② 설계 원칙 & 고려 사항

- **단일 진입점 + OOP 분리** — `index.py` 는 트리거 파싱/응답 매핑만, 도메인 로직은 `service.py`/`consumer.py`/`repository.py`/`keys.py` 로 분리합니다.
- **이중 import** — `try: from .x import ... except ImportError: from x import ...`. 패키지(레포·테스트)와 평면 zip(Lambda)을 모두 지원합니다.
- **알고리즘 핀** — 예약 토큰은 RS256, 인증 토큰은 HS256, 캡차는 HMAC-SHA256 으로 고정해 alg confusion 을 차단합니다.
- **CORS 직접 처리** — REST `AWS_PROXY` 경로(ticketing/captcha)는 OPTIONS 204 + CORS 헤더를 Lambda 가 직접 응답합니다(`Reservation` 헤더 허용, `Max-Age=600`).
- **시크릿 lazy** — 시크릿 의존 서비스(ticketing/captcha)는 콜드스타트 INIT 가 아니라 첫 invoke 에서 생성합니다.
- **fail-closed / 멱등 / 순서 보존** — authorizer 는 오류 시 Deny, persistence 는 `ON CONFLICT DO NOTHING` + FIFO 순서 유지로 안전하게 동작합니다.

## ③ 구성

```
domains/
├── ticketing/    index.py  service.py  requirements.txt   # pyjwt[crypto], redis
├── authorizer/   index.py  service.py  keys.py  requirements.txt   # pyjwt[crypto]
├── persistence/  index.py  consumer.py  repository.py  requirements.txt   # psycopg2-binary
└── captcha/      index.py  service.py                     # 외부 의존 없음
```

---

## ticketing

> 상세: [ticketing/README.md](./ticketing/README.md)

> **대기열 순번 발급·조회**, 입장 순번 도달 시 **입장 토큰(JWT, RS256)** 발급. 토큰 버킷으로 입장률을 다운스트림(reservation pod) 수용량에 맞춥니다.

### 책임

| 파일 | 책임 |
|------|------|
| `index.py` | OPTIONS 204, `event_id`(pathParameters)·`user_id`(access token) 추출, 응답 매핑 |
| `service.py` | `QueueService` — Redis 대기열·토큰버킷·RS256 토큰 발급 |

### 동작

**index.py**
- OPTIONS → 204 + CORS 헤더 (프리플라이트).
- `event_id` = `pathParameters.event_id`. 누락 시 빈 키(`queue:`/`current:`) 공유로 이벤트 간 충돌이 나므로 **400** 으로 빠르게 거부합니다.
- `user_id` — 큐 라우트는 API GW `authorization=NONE` 이라 Lambda 가 `Authorization` 헤더의 **access token 을 직접 검증**(HS256, `type=="access"`, `sub` 추출). 무효 시 **401**. 인증 토큰의 `aud` 규약은 미정이라 검증하지 않습니다.
- 정상 → `QueueService.issue()` 결과를 200 으로 반환(`WAITING` / `COMPLETED`).

**service.py — `QueueService`**, Redis Lua 스크립트 3개로 원자성 보장:

| 스크립트 | 역할 |
|----------|------|
| `_NUMBER_LUA` | 번호 발급 — 캐시 있으면 재사용, 없으면 `INCR`+`SET EX`. 동시 최초요청의 중복 INCR(issued inflation) 방지 |
| `_ADMIT_LUA` | 입장 커서(`current`) 토큰버킷 전진. `redis TIME` 으로 클럭 일원화, rate/capacity 만큼 토큰 충전 후 대기자 수만큼만 입장 |
| `_PODS_LUA` | 라이브 reservation pod 수 — 만료 하트비트(ZSET) 제거 후 `ZCARD` |

핵심 흐름:
- **토큰 버킷** rate·capacity 를 **라이브 pod 수에 비례**(`pods * 초당입장`, `pods * 버스트`)시켜 입장률을 오토스케일되는 다운스트림 수용량에 맞춥니다. 하트비트가 없으면 최소 1 pod 로 간주(최소 배출 보장).
- `remaining = queue_number - current` 가 0 이하면 `COMPLETED` → 입장 토큰 발급, 아니면 `WAITING`(`queue_number`/`remaining`).
- **RS256 서명키**는 Secrets Extension 에서 lazy 조회하고, 콜드스타트에 PEM 유효성을 미리 검증(`RSAAlgorithm.prepare_key`)해 발급 시점의 모호한 500 을 피합니다. 토큰 클레임: `user_id`/`event_id`/`aud=reservation_waiting`/`iat`/`exp`.

### 응답 예

```jsonc
// WAITING
{ "code": "WAITING",  "message": "현재 대기열", "data": { "queue_number": 1024, "remaining": 37 } }
// COMPLETED
{ "code": "COMPLETED","message": "입장 순번이 되었습니다.", "data": { "token": "<RS256 JWT>" } }
```

---

## authorizer

> 상세: [authorizer/README.md](./authorizer/README.md)

> API Gateway **REST REQUEST authorizer**. 예약 토큰(RS256)·인증 토큰(HS256)을 함께 검증하고 두 `user_id` 가 같으면 Allow. IAM 정책 문서를 반환합니다.

### 책임

| 파일 | 책임 |
|------|------|
| `index.py` | 헤더 정규화, IAM 정책 생성, 오류 → API Gateway 응답 매핑(401/403/fail-closed) |
| `service.py` | `AuthorizerService` — 헤더 추출·이중 토큰 검증·동일 유저 판별 |
| `keys.py` | `KeyProvider` — 예약 공개키(CloudFront) + 인증 대칭키(Secrets Extension) |

### 동작

**index.py**
- 헤더를 소문자로 정규화 후 `AuthorizerService.authorize()` 호출.
- `MissingCredentialError` → `raise Exception("Unauthorized")` — API Gateway 가 정확히 이 메시지를 **401** 로 매핑합니다.
- `AuthorizationError`(서명 무효·클레임 누락·유저 불일치) → **Deny(403)**.
- 그 외 예외(키 조회 실패·설정 누락) → **fail-closed Deny** (열려버리는 500 회피).
- Allow 시 Resource 를 `{apiId}/{stage}/*/*` **와일드카드**로 둡니다. authorizer Allow 는 `identity=Reservation` 헤더 기준으로 캐시(기본 TTL 300s)되므로, 특정 `methodArn` 으로 좁히면 첫 요청(예: GET) 정책이 캐시돼 다른 메서드(예: DELETE)가 403 이 됩니다. `context.user_id` 로 백엔드(`$context.authorizer.user_id`)에 전달합니다.

**service.py — `AuthorizerService`**
- `Reservation` / `Authorization` 헤더 추출(`Bearer ` 접두사 허용, 단일 토큰도 허용, 비정상 포맷은 누락으로 간주).
- 예약 토큰 RS256 검증(`aud=RESERVATION_AUDIENCE`) → `user_id` 클레임 = `user_id`.
- 인증 토큰 HS256 검증(`aud` 미검증) → `user_id` 클레임 = `sub`.
- 두 `user_id` 가 다르면 `InvalidCredentialError`(불일치는 본문 비노출, 로그만). 클레임 검증은 `None`·빈 문자열만 거부하고 `0` 같은 falsy 값은 유효 식별자로 허용합니다.

**keys.py — `KeyProvider`**
- 예약 공개키: **CloudFront URL** 로 fetch. non-VPC authorizer 라 S3 IAM 이 불필요하며, 회전이 드물어 **인스턴스 캐시**(최초 1회 fetch). 평문(http)은 MITM 키 변조로 검증 우회 위험이 있어 **https 만 허용**합니다.
- 인증 대칭키: Secrets Extension 캐시 조회(짧은 타임아웃 2s).

> 과거 README 는 공개키를 S3(`PUBLIC_KEY_BUCKET`)로 적었으나, 실제 코드는 **CloudFront URL(`PUBLIC_KEY_URL`)** 입니다(#52 전환). 본 문서가 코드 기준입니다.

---

## persistence

> 상세: [persistence/README.md](./persistence/README.md)

> SQS **FIFO** 소비 → **RDS#2**(reservation/payment) **멱등 적재**. batchSize + reserved concurrency 로 DB 유입을 제한하는 **leaky bucket consumer**.

### 책임

| 파일 | 책임 |
|------|------|
| `index.py` | 모듈 로드 시 `PersistenceConsumer` 생성, `consume(event)` 위임 |
| `consumer.py` | `PersistenceConsumer` — 그룹화·순차 처리·부분 실패·action 분기 |
| `repository.py` | `ReservationRepository` — psycopg2 커넥션 재사용·멱등 SQL |

### 동작

**consumer.py — `PersistenceConsumer`**
- `Records` 를 `MessageGroupId` 별로 그룹화 → 그룹 내 순차 처리(그룹 간 독립).
- 그룹 내 **첫 실패부터 끝까지** `batchItemFailures` 로 반환해 FIFO 순서를 보존(앞 메시지를 건너뛰지 않음).
- action 분기: `reservation.create` / `reservation.cancel` / `payment.create`. **미지의 action 은 raise** → 재처리해도 동일 실패이므로 DLQ 로 격리됩니다.
- `OperationalError`(RDS 페일오버 등 일시 오류)는 커넥션을 `reset()`(폐기) 후 해당 인덱스부터 SQS 재처리에 위임. 그 외 예외는 `rollback()` 후 실패 인덱스 반환.

**repository.py — `ReservationRepository`**
- psycopg2 커넥션을 **재사용**(`closed` 면 재연결). `insertReservation`/`cancelReservation`/`insertPayment` + `commit`/`rollback`/`reset`.
- INSERT 는 PK 기준 **`ON CONFLICT DO NOTHING`** 으로 멱등(중복 메시지 재처리 안전).

> **배포(infra)**: 이벤트 소스 매핑 `batchSize=10`, reserved concurrency 5~10. 두 값이 DB 유입 속도(leaky bucket)를 결정합니다. 메시지 계약은 app repo 의 `reservation/payment messages.py` 와 공유합니다.

---

## captcha

> 상세: [captcha/README.md](./captcha/README.md)

> **ALTCHA PoW 캡차 챌린지** 발급(공개 경로). 봇 차단용이며 **외부 의존 없이 stdlib 만**으로 구현됩니다.

### 책임

| 파일 | 책임 |
|------|------|
| `index.py` | OPTIONS 처리, 시크릿 lazy 조회, `issue_challenge()` 응답 |
| `service.py` | `CaptchaService` — 챌린지 생성·검증(HMAC 서명·상수시간 비교) |

### 동작

**index.py**
- OPTIONS → 204 + CORS. 공개 경로지만 클라가 `Authorization`/`Reservation` 을 함께 실어 보내므로 프리플라이트를 허용합니다.
- 시크릿은 첫 invoke 때 lazy 조회(콜드스타트 INIT 시 Extension 미준비 → 크래시 회피). `CAPTCHA_SECRET_ID` 없으면 `CaptchaConfigError`.

**service.py — `CaptchaService`**
- **발급(`issue_challenge`)** — `number`(PoW 정답)를 `0..complexity` 에서 무작위 선택 → `salt = token_hex.expires` → `challenge = SHA256(salt+number)` → `signature = HMAC-SHA256(secret, challenge)`. 클라이언트는 brute-force 로 `number` 를 찾습니다.
- **검증(`verify`)** — base64 엄격 디코딩 → 알고리즘/타입 확인 → 만료(`expires`) 확인 → `challenge` 해시 일치 → HMAC 서명 일치. 비교는 모두 `hmac.compare_digest`(상수시간)로 타이밍 공격을 차단합니다.
- WAS(검증측)와 **동일 HMAC 시크릿을 공유**합니다(이 Lambda 는 발급, 검증은 양측 가능). `complexity` 0 이하 입력은 `randbelow` ValueError 방지를 위해 최소 1 로 보정합니다.

---

## ⑤ 환경변수 · 의존

| 도메인 | 환경변수 | 의존 |
|--------|----------|------|
| ticketing | `REDIS_HOST`/`REDIS_PORT`, `RESERVATION_SECRET_ID`, `AUTHORIZATION_SECRET_ID`, `RESERVATION_TOKEN_TTL_SECONDS`(600), `QUEUE_PER_POD_ADMIT_PER_SECOND`/`QUEUE_PER_POD_BURST`/`QUEUE_INITIAL_ADMIT` | pyjwt[crypto], redis |
| authorizer | `PUBLIC_KEY_URL`, `AUTHORIZATION_SECRET_ARN`, `RESERVATION_AUDIENCE`(reservation_waiting), `RESERVATION_USER_CLAIM`(user_id), `AUTHORIZATION_USER_CLAIM`(sub) | pyjwt[crypto] |
| persistence | `RESERVATION_DB_URL` | psycopg2-binary |
| captcha | `CAPTCHA_SECRET_ID`, `CAPTCHA_HMAC_SECRET`(fallback), `CAPTCHA_COMPLEXITY`(100000) | stdlib 전용 |

> 공통 시크릿 조회·로깅은 [../common/README.md](../common/README.md) 참고. 시크릿 값은 env 에 두지 않고 이름/ARN 만 주입합니다.

---

⬆ [lambda 대표 README로](../README.md)
