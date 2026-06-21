# ticketing (lambda 도메인)

## 개요

대기열 **순번 발급·조회**를 담당하고, 입장 순번에 도달하면 **입장 토큰(JWT, RS256)**을 발급하는 waiting-room/queue entry Lambda. 토큰 버킷으로 입장률을 다운스트림(reservation pod) 수용량에 맞춥니다. ElastiCache(Redis) 접근을 위해 **VPC-attached** 로 동작합니다.

## 트리거 · 핸들러

- **트리거**: API Gateway(REST, ANY→`AWS_PROXY`) — `/queue/{event_id}` GET. 큐 라우트는 API GW `authorization=NONE` 이라 Lambda 가 access token 을 직접 검증합니다.
- **핸들러**: `domains.ticketing.index.lambda_handler` → `QueueService.issue(event_id, user_id)` 위임.

| 파일 | 책임 |
|------|------|
| `index.py` | OPTIONS 204, `event_id`(pathParameters)·`user_id`(access token) 추출, 응답 매핑 |
| `service.py` | `QueueService` — Redis 대기열·토큰버킷·RS256 토큰 발급 |

## 핵심 동작

- **CORS 직접 처리** — OPTIONS → 204 + CORS 헤더(`Reservation` 허용, `Max-Age=600`, 폴링 프리플라이트 캐시).
- **입력 검증** — `event_id` 누락 시 빈 키(`queue:`/`current:`) 공유로 이벤트 간 충돌이 나므로 **400**. `Authorization` 헤더의 access token 을 HS256 으로 직접 검증(`type=="access"` 확인, `sub` 추출), 무효 시 **401**. 시크릿은 코드 캐시 없이 Secrets Extension 캐시만 신뢰합니다.
- **원자적 번호 발급** — `_NUMBER_LUA`: 캐시 있으면 재사용, 없으면 `INCR`+`SET EX`. 동시 최초요청의 중복 INCR(issued inflation)을 방지합니다.
- **토큰 버킷 입장** — `_ADMIT_LUA`: `redis TIME` 으로 클럭 일원화, rate·capacity 를 **라이브 pod 수에 비례**(`pods * 초당입장`, `pods * 버스트`)시켜 입장 커서(`current`)를 전진. 하트비트가 없으면 최소 1 pod 로 간주(최소 배출 보장). `_PODS_LUA` 가 만료 하트비트(ZSET) 제거 후 `ZCARD` 로 라이브 pod 수를 셉니다.
- **결과 분기** — `remaining = queue_number - current` 가 0 이하면 `COMPLETED`(입장 토큰 발급), 아니면 `WAITING`(`queue_number`/`remaining`).
- **RS256 토큰** — 서명키는 Secrets Extension 에서 lazy 조회하고 콜드스타트에 PEM 유효성을 미리 검증(`RSAAlgorithm.prepare_key`)해 발급 시점의 모호한 500 을 피합니다. 클레임: `user_id`/`event_id`/`aud=reservation_waiting`/`iat`/`exp`.

## 의존 (AWS 서비스 · env)

- **AWS**: API Gateway(REST, AWS_PROXY), ElastiCache(Redis), Secrets Manager + Parameters/Secrets Extension, VPC.
- **라이브러리**: `pyjwt[crypto]`(jwt-layer), `redis`(redis-layer).

| 환경변수 | 설명 |
|----------|------|
| `REDIS_HOST` / `REDIS_PORT` | ElastiCache(Redis) 엔드포인트 (기본 포트 6379) |
| `RESERVATION_SECRET_ID` | RS256 서명용 RSA 개인키 Secrets Manager 이름 |
| `AUTHORIZATION_SECRET_ID` | access token(HS256) 검증 대칭키 이름 |
| `RESERVATION_TOKEN_TTL_SECONDS` | 입장 토큰 유효시간 (기본 `600`) |
| `QUEUE_PER_POD_ADMIT_PER_SECOND` / `QUEUE_PER_POD_BURST` / `QUEUE_INITIAL_ADMIT` | 토큰버킷 rate·capacity·초기 입장 |

> 공통 시크릿 조회는 [../../common/README.md](../../common/README.md) 참고. 시크릿 값은 env 에 두지 않고 이름만 주입합니다.

---
⬆ [domains README로](../README.md)
