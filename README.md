# Cloud Crusade · Lambda

> 대규모 티켓팅 트래픽을 **제어·인증·적재**하는 AWS Lambda 모음.
> 메인 백엔드(WAS, app repo)와 분리된 **서버리스 엣지/비동기 처리 계층**입니다.

대기열 순번·입장 토큰 발급(트래픽 제어), API Gateway REQUEST authorizer 이중 토큰 검증, SQS FIFO → RDS 멱등 적재(leaky bucket), ALTCHA PoW 캡차 챌린지(봇 차단)를 도메인별 독립 Lambda 로 제공합니다.

## 1. 프로젝트 소개

수만 명이 동시에 몰리는 티켓 오픈 순간, WAS 가 직접 받아내기 어려운 트래픽을 **엣지에서 줄세우고(대기열) → 검증하고(authorizer) → 천천히 흘려보내는(leaky bucket 적재)** 일을 담당합니다. 각 기능은 별도 Lambda 함수이며, DDD 모듈 구조(`domains/<도메인>/`)로 자기완결적으로 패키징됩니다.

| 구분 | 스택 |
|------|------|
| 언어 | Python (코드 `str \| None` 문법 = 3.10+, 배포 wheel `--python-version 3.11`) |
| 인증/토큰 | PyJWT[crypto] — 예약 토큰 RS256, 인증/캡차 HS256·HMAC |
| 데이터 | redis (대기열·토큰버킷), psycopg2-binary (RDS PostgreSQL) |
| 캡차 | Python stdlib 전용 (`hashlib`/`hmac`/`secrets`) — 외부 의존 없음 |
| AWS | Lambda, API Gateway(REST · AWS_PROXY + REQUEST authorizer), SQS FIFO, ElastiCache(Redis), Secrets Manager + Parameters/Secrets Extension, S3/CloudFront(공개키), RDS(PostgreSQL) |
| 배포 | 도메인별 zip — CI 가 `common/` 복사 + requirements 를 manylinux wheel 로 번들 → S3 |

## 2. 설계 방향 & 고려 사항

전체를 관통하는 원칙은 아래와 같습니다. **상세 근거·동작은 각 모듈 README 로 위임**합니다.

- **단일 진입점 규약** — 모든 Lambda 는 `domains.<도메인>.index.lambda_handler` 하나로 통일하고, 로직은 OOP 파일(`service.py` / `consumer.py` / `repository.py` / `keys.py`)로 분리합니다.
- **이중 import 패턴** — `try: from .service import ... except ImportError: from service import ...`. 레포·테스트(패키지)와 평면 zip(Lambda) 양쪽에서 동작합니다.
- **시크릿은 값이 아닌 이름/ARN 만 env 로** — Parameters/Secrets Lambda Extension 의 로컬 캐시(`localhost:2773`)로 조회하여 키 회전을 **무재배포** 반영합니다. → [common/README.md](common/README.md)
- **콜드스타트 회피 (lazy)** — Secrets Extension 은 INIT 시점에 ready 가 아니므로, 시크릿 의존 서비스는 첫 invoke 때 `_get_service()` 로 lazy 생성합니다.
- **알고리즘 핀** — JWT 검증 시 `algorithms=[...]` 를 RS256/HS256 으로 고정해 alg confusion 공격을 차단합니다.
- **CORS 직접 처리** — REST API 가 `AWS_PROXY` 라 OPTIONS 프리플라이트/CORS 헤더를 Lambda 가 직접 응답합니다(`Reservation` 헤더 허용, `Max-Age=600`).
- **fail-closed** — authorizer 는 예상치 못한 오류에서도 Deny 를 반환합니다(열려버리는 500 회피).
- **유입 제어 알고리즘** — 입장은 **token bucket**(ticketing, reservation pod 수 비례), DB 적재는 **leaky bucket**(persistence, batchSize + reserved concurrency)로 다운스트림 수용량을 추종합니다.

> 자세한 도메인별 설계·로직은 [domains/README.md](domains/README.md) 에 정리되어 있습니다.

## 3. 아키텍처 개요

```
                            ┌──────────────────────────────────────┐
   Client ──/captcha──────► │ captcha  (ALTCHA PoW 챌린지, 공개경로) │
                            └──────────────────────────────────────┘
                            ┌──────────────────────────────────────┐
   Client ──/queue/{id}───► │ ticketing (Redis 대기열 + 입장 토큰)  │
     (access token, HS256)  │   WAITING / COMPLETED(RS256 토큰)     │
                            └──────────────────────────────────────┘
                                          │ COMPLETED → 예약 토큰(RS256)
                                          ▼
   Client ──예약 경로──► API Gateway ─REQUEST authorizer─► ┌───────────────┐
     (Reservation + Authorization)                        │ authorizer    │
                                                          │ RS256 + HS256 │
                                                          │ 동일 유저 → Allow│
                                                          └───────┬───────┘
                                                            Allow │ context.user_id
                                                                  ▼
                                                               WAS (app)
                                                                  │ 예약/결제 이벤트
                                                                  ▼
                                                         SQS FIFO 큐
                                                                  │ batchSize 10
                                                                  ▼
                            ┌──────────────────────────────────────┐
                            │ persistence (leaky bucket consumer)   │
                            │ action 분기 → RDS#2 멱등 적재          │
                            └──────────────────────────────────────┘
```

## 4. 모듈 구성

```
lambda/
├── common/                 # 도메인 공통 모듈
│   ├── logging.py          # getLogger(name) — INFO 표준 로거
│   └── secrets.py          # get_secret_string() — Secrets Extension 캐시 조회
├── domains/                # DDD 도메인별 자기완결 모듈
│   ├── ticketing/          # 대기열 순번 + 입장 토큰(RS256) 발급
│   │   ├── index.py  service.py  requirements.txt
│   ├── authorizer/         # REQUEST authorizer — 예약·인증 토큰 동시 검증
│   │   ├── index.py  service.py  keys.py  requirements.txt
│   ├── persistence/        # SQS FIFO → RDS 멱등 적재(leaky bucket)
│   │   ├── index.py  consumer.py  repository.py  requirements.txt
│   └── captcha/            # ALTCHA PoW 챌린지 발급 (stdlib 전용)
│       ├── index.py  service.py
├── test/                   # 소스 1:1 미러링 unittest
└── .github/workflows/      # lambda-deploy.yml(CD) · convention_check.yml(CI)
```

| 모듈 | 책임 | 진입점 | 주요 의존 | 세부 |
|------|------|--------|-----------|------|
| common | 공통 로거 · Secrets Extension 조회 | (라이브러리) | stdlib | [common/README.md](common/README.md) |
| ticketing | 대기열 순번·입장 토큰(RS256) 발급 | `domains.ticketing.index` | pyjwt[crypto], redis | [domains/README.md](domains/README.md#ticketing) |
| authorizer | 예약+인증 토큰 동시 검증 → IAM 정책 | `domains.authorizer.index` | pyjwt[crypto] | [domains/README.md](domains/README.md#authorizer) |
| persistence | SQS FIFO → RDS#2 멱등 적재 | `domains.persistence.index` | psycopg2-binary | [domains/README.md](domains/README.md#persistence) |
| captcha | ALTCHA PoW 챌린지 발급 | `domains.captcha.index` | stdlib 전용 | [domains/README.md](domains/README.md#captcha) |

**읽는 순서**: [common/README.md](common/README.md) → [domains/README.md](domains/README.md)

## 5. 실행 방법

### 로컬 테스트 (의존성 불필요)

테스트는 stdlib `unittest` 만 사용하며, 외부 드라이버(`psycopg2`/`jwt`/`redis`)는 각 테스트 상단에서 `sys.modules` 스텁으로 주입합니다. `PYTHONPATH` 는 레포 루트 기준입니다.

```bash
cd lambda
python -m unittest discover -s test                       # 전체
python -m unittest test/domains/persistence/test_consumer.py   # 개별
```

> 통합(실드라이버) 실행에는 `pyjwt[crypto]` / `redis` / `psycopg2-binary` 가 필요합니다.

### CI 패키징·배포 (`lambda-deploy.yml` — "lambda cd")

`main` 대상 PR merged(closed) 또는 수동 트리거 시 동작합니다.

1. AWS 자격 증명 구성(`ap-northeast-2`)
2. `domains/*` 각각에 `common/` 복사 + requirements 를 manylinux wheel 로 번들
   `pip install -t . --platform manylinux2014_x86_64 --python-version 3.11 --only-binary=:all:`
3. `<name>.zip` 생성 → `aws s3 cp dist/ s3://tfstate-bucket-d8f5bb8d/lambda/ --recursive`, `dist/lambda-modules.txt` 기록
4. 실제 함수 갱신 / Layer / env 주입은 **infra(terraform)** 가 담당

`convention_check.yml` 은 모든 PR 에서 commit-lint + pr-title-lint 만 수행합니다(테스트 자동 실행 없음).

### Layer

| 레이어 | 설명 |
|--------|------|
| redis-layer | redis (ticketing) |
| psycopg2-layer | psycopg2 (persistence) |
| jwt-layer | PyJWT + cryptography (RS256/HS256 — ticketing·authorizer) |
| secrets-extension | AWS Parameters and Secrets Lambda Extension (관리형) |

> README Layer 표기와 배포 wheel(`--python-version 3.11`), 코드 문법(3.10+)에 런타임 버전 표기가 혼재합니다. 함수 런타임은 infra(terraform) 설정이 기준입니다.

## 6. 컨벤션 합의 사항

팀 내 협업의 효율 및 생산성을 위한 규약 — CI(`convention_check.yml`)가 commit-lint · pr-title-lint 로 강제합니다(Merge/Revert 예외).

### Github 컨벤션

**Issue** — 템플릿 준수, 타이틀 `[카테고리]: 이슈 제목`
- Feature: 기능 추가, 기능 변경
- Refactor: 리팩토링, 구조 변경
- Bug: 발생한 버그 목록
- Chore: 의존성, 문서 작업 등 코드 외 작업

EX `[Feature] OAuth 2.0 추가` / `[Refactor] Ansible 모듈 리팩토링`

**Branch** — `카테고리/#이슈번호/브랜치명`
- feature / refactor / fix / chore

**Commit** — `[카테고리]: 커밋 내용`
- FEAT: 기능 추가, 기능 변경
- REFAC: 리팩토링, 구조 변경
- FIX: 버그 수정, 오류 수정
- CHORE: 의존성 추가, 코드 외 작업

EX `[FEAT]: OAuth2.0 추가 - Google, Naver Authentication` / `[CHORE]: pytest 의존성 추가`

**Pull Request** — 템플릿 준수, 제목 `[카테고리#이슈번호] PR 제목` (카테고리는 커밋과 동일)

EX `[FEAT#18] Google, Naver OAuth 2.0 추가`

### Code 컨벤션

**Naming**
- **Class** — PascalCase. 명명된 모델·엔티티에 맞춰 작성, 객체 지향 원칙에 따른 엔티티 작성, 필요 시 추상 클래스 상속. EX `class User`, `class Payment`
- **Method** — camelCase. public 은 일반문자, private 은 언더바(`_`) 시작. parameter 는 엔티티 요소를 함축, RESTful 키워드보다 동작 방식 기준 명명. EX `def getUser()`, `def createUser()`
- **Variable** — snake_case. 사용처·알고리즘·아키텍처에 맞는 명칭, 의미 없는 변수(`data1` 등) 금지, 속성 변수는 외부 사용 최대한 배제. EX `user = User()`

**Architecture** — DDD 기반 모듈형 설계. `common`: 공용 모듈 / `domains`: 서비스 도메인별 모듈

> 테스트: stdlib `unittest`(pytest/conftest 없음), 각 파일 상단에 실행법 기재, 외부 드라이버는 `sys.modules` 스텁으로 주입(`setdefault` 가산식), 소스 1:1 미러링. CI 는 린트만 수행.

## 7. 팀원 작업 역할

| 담당자 | 역할 |
|--------|------|
| juhy0987 (김주현) | 도메인 로직 전반 메인테이너 — authorizer/ticketing/persistence/captcha/common 거의 전 도메인, 버그픽스·리팩토링 |
| mshjgr | 초기 큐 도메인 부트스트랩 — #2 UUID+SQS 등록, #6 Redis 대기열, #8 logging+README |
| hjh1346 | 배포 파이프라인(#21 lambda CD) + EventBridge 작업(#61 open) |

> **로드맵**: PR #61(open, hjh1346)이 `domains/bot_block/`, `domains/bot_check/`(EventBridge 기반 봇 탐지/차단)를 추가할 예정입니다. 아직 `main` 미반영이므로 본 문서는 4개 도메인 기준이며, 봇 차단 도메인은 **합류 예정**입니다.

## 8. 참고

- **app repo (WAS)** — 메인 백엔드. 캡차 검증측과 HMAC 시크릿 공유, SQS 메시지 계약(`reservation/payment messages.py`) 공유, authorizer `context.user_id` 소비.
- **infra repo (terraform)** — 함수/Layer/env/이벤트 소스 매핑(batchSize·reserved concurrency)/CloudFront·Secrets·RDS 프로비저닝.
- 모듈 세부: [common/README.md](common/README.md) · [domains/README.md](domains/README.md)
