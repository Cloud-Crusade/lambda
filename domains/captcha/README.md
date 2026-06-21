# captcha (lambda 도메인)

## 개요

**ALTCHA PoW 캡차 챌린지**를 발급하는 공개 경로 Lambda. 봇 차단용이며 외부 의존 없이 **stdlib 만**(`hashlib`/`hmac`/`secrets`)으로 구현됩니다. **non-VPC** 로 동작합니다.

## 트리거 · 핸들러

- **트리거**: API Gateway(REST, `AWS_PROXY`) — `/captcha/challenge` GET. 공개 경로지만 클라가 `Authorization`/`Reservation` 을 함께 실어 보내므로 OPTIONS 프리플라이트를 허용합니다.
- **핸들러**: `domains.captcha.index.lambda_handler` → `CaptchaService.issue_challenge()` 위임.

| 파일 | 책임 |
|------|------|
| `index.py` | OPTIONS 204 + CORS, 시크릿 lazy 조회, `issue_challenge()` 응답 매핑 |
| `service.py` | `CaptchaService` — 챌린지 생성·검증(HMAC 서명·상수시간 비교) |

## 핵심 동작

- **CORS 직접 처리** — `httpMethod == OPTIONS` 면 204 + CORS 헤더(`Reservation` 허용, `Max-Age=600`)로 응답합니다.
- **시크릿 lazy** — 첫 invoke 때 `_get_service()` 로 HMAC 시크릿을 조회(콜드스타트 INIT 시 Extension 미준비 → 크래시 회피). `CAPTCHA_SECRET_ID` 없으면 `CaptchaConfigError`.
- **챌린지 발급(`issue_challenge`)** — `number`(PoW 정답)를 `0..complexity` 에서 무작위 선택 → `salt = token_hex.expires` → `challenge = SHA256(salt+number)` → `signature = HMAC-SHA256(secret, challenge)`. 클라이언트는 brute-force 로 `number` 를 찾습니다. 응답: `algorithm`/`challenge`/`maxnumber`/`salt`/`signature`.
- **검증(`verify`)** — base64 엄격 디코딩 → 알고리즘/타입 확인 → 만료(`expires`) 확인 → `challenge` 해시 일치 → HMAC 서명 일치. 비교는 모두 `hmac.compare_digest`(상수시간)로 타이밍 공격을 차단합니다.
- **시크릿 공유** — WAS(검증측)와 동일 HMAC 시크릿을 공유합니다(이 Lambda 는 발급, 검증은 양측 가능). `complexity` 0 이하 입력은 `randbelow` ValueError 방지를 위해 최소 1 로 보정합니다.

## 의존 (AWS 서비스 · env)

- **AWS**: API Gateway(REST, AWS_PROXY), Secrets Manager + Parameters/Secrets Extension(HMAC 시크릿). non-VPC.
- **라이브러리**: stdlib 전용(외부 의존 없음).

| 환경변수 | 설명 |
|----------|------|
| `CAPTCHA_SECRET_ID` | HMAC 시크릿 Secrets Manager 이름/ARN |
| `CAPTCHA_HMAC_SECRET` | HMAC 시크릿 직접 주입(fallback, env) |
| `CAPTCHA_COMPLEXITY` | PoW 난이도 = `maxnumber` (기본 `100000`) |

> 공통 시크릿 조회는 [../../common/README.md](../../common/README.md) 참고.

---
⬆ [domains README로](../README.md)
