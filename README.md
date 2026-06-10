# Lambda Service

## Overview
티켓팅 서비스의 대기열 관리를 담당하는 Lambda 함수 모음입니다.

- user_id 기반 사용자 식별
- Redis를 활용한 대기열 순번 발급
- 중복 요청 방지 (아토믹 처리)
- 대기열 앞 순번 실시간 계산

## Directory Structure
```
lambda/
├── common/                   # 도메인 공통 모듈
│   └── logging.py
├── domains/                  # 서비스 도메인별 모듈 (DDD)
│   ├── ticketing/            # 대기열 순번 / 입장 토큰 도메인
│   │   ├── index.py          # 진입점 (lambda_handler)
│   │   └── service.py        # QueueService (대기열·토큰 로직)
│   ├── authorizer/           # API Gateway REQUEST authorizer (예약+인증 토큰 동시 검증)
│   │   ├── index.py          # 진입점 (lambda_handler) — IAM 정책(Allow/Deny) 반환
│   │   ├── service.py        # AuthorizerService (이중 토큰 검증·동일 유저 판별)
│   │   └── keys.py           # KeyProvider (S3 공개키 + Secrets Manager 대칭키, 인스턴스 캐시)
│   └── persistence/          # 예약·결제 FIFO 큐 → RDS#2 적재 (leaky bucket)
│       ├── index.py          # 진입점 (lambda_handler)
│       ├── consumer.py       # PersistenceConsumer (소비·순서·부분 실패)
│       └── repository.py     # ReservationRepository (DB 적재)
├── test/                     # 아키텍처 구조를 미러링한 테스트
│   └── domains/
│       ├── authorizer/
│       │   └── test_service.py
│       └── persistence/
│           └── test_consumer.py
└── README.md
```
> **진입점은 도메인별 `index.py` 의 `lambda_handler` 함수로 통일**합니다. 구현은 같은 디렉토리의 다른 파일(OOP)로 분리하고, 공통 모듈은 `common/` 에 둡니다.
> Lambda handler 설정값: `domains.<도메인>.index.lambda_handler`

## Architecture
요청 흐름은 다음과 같습니다.

1. **순번 조회 / 입장 토큰** — Client → API Gateway → `ticketing`
   - Redis로 대기열 순번 발급·조회
   - 입장 순번 도달 시 입장 토큰(JWT, `aud=reservation_waiting`) 발급
2. **입장 검증** — API Gateway 가 예약 경로에 `authorizer` Lambda(REQUEST authorizer)를 붙여 **두 토큰을 함께 검증**
   - `Reservation` 헤더의 예약 토큰을 S3 공개키로 **RS256** 검증
   - `Authorization` 헤더의 인증 토큰을 Secrets Manager 대칭키로 **HS256** 검증
   - 두 토큰의 `user_id` 가 같으면 Allow, 다르거나 서명 무효면 Deny(403), 자격 증명 누락이면 401
3. **예약·결제 적재** — WAS가 단일 SQS FIFO 큐로 발행 → `persistence` Lambda가 leaky bucket으로 소비해 RDS#2(reservation/payment)에 적재
   - 한 번에 최대 10건(batchSize) 수신, 예약 동시성(reserved concurrency) 5~10으로 DB 유입 속도 제한
   - `messageGroupId` 단위 순서 보장(FIFO), 그룹 내 첫 실패부터는 `batchItemFailures`로 반환해 SQS 재처리

## Lambda Functions

### ticketing (domains/ticketing — `index.lambda_handler`)
| 항목 | 내용 |
|------|------|
| 역할 | 대기열 순번 발급·조회, 입장 순번 도달 시 입장 토큰(JWT) 발급 |
| 입력 | event_id, user_id |
| 출력 | code(WAITING / COMPLETED), message, data(queue_number·remaining 또는 token) |
| 구현 | `service.QueueService` (Redis 대기열 + JWT 발급) |
| 특이사항 | 동일 user_id 재요청 시 기존 번호 반환 |

### authorizer (domains/authorizer — `index.lambda_handler`)
| 항목 | 내용 |
|------|------|
| 역할 | 예약 토큰(RS256)·인증 토큰(HS256)을 함께 검증하고 동일 유저인지로 인가 |
| 입력 | API Gateway REQUEST authorizer event — `Reservation`·`Authorization` 헤더 |
| 출력 | IAM 정책 문서(Allow/Deny). 누락 시 `Unauthorized` 예외(→401) |
| 구현 | `service.AuthorizerService` + `keys.KeyProvider` |
| 특이사항 | 공개키는 인스턴스 캐시, 대칭키는 Secrets Extension(로컬 캐시)로 조회, 알고리즘 핀(RS256/HS256)으로 confusion 방지 |
| 의존 | PyJWT + cryptography (Layer), Secrets Extension (Layer), boto3(런타임 기본) |

### persistence (domains/persistence — `index.lambda_handler`)
| 항목 | 내용 |
|------|------|
| 역할 | 예약·결제 FIFO 큐 메시지를 RDS#2에 멱등 적재 (leaky bucket consumer) |
| 입력 | SQS event (Records) — action: reservation.create / reservation.cancel / payment.create |
| 출력 | `{"batchItemFailures": [...]}` (부분 실패 보고) |
| 구현 | `consumer.PersistenceConsumer` + `repository.ReservationRepository` |
| 특이사항 | PK 기준 ON CONFLICT DO NOTHING 멱등 처리, OperationalError 시 SQS 재처리 위임 |
| 배포 설정 | event source mapping `batchSize=10`, reserved concurrency 5~10 (infra에서 지정) |
| 의존 | psycopg2 (Layer), `RESERVATION_DB_URL` |

## Environment Variables
| 변수명 | 설명 | 예시 |
|--------|------|------|
| REDIS_HOST | ElastiCache 엔드포인트 주소 (ticketing) | xxx.cache.amazonaws.com |
| REDIS_PORT | Redis 포트 (ticketing) | 6379 |
| RESERVATION_SECRET_ID | 입장 토큰 서명용 예약 RSA 개인키의 Secrets Manager 시크릿 이름/ARN (ticketing, 확장 캐시 조회) | dev-reservation-private-key |
| RESERVATION_DB_URL | RDS#2(reservation/payment) 접속 URL (persistence) | postgresql://user:pass@host:5432/reservation |
| PUBLIC_KEY_BUCKET | Reservation 공개키가 있는 S3 버킷 (authorizer) | my-public-bucket |
| PUBLIC_KEY_KEY | Reservation 공개키 S3 키 (authorizer) | jwt/dev/reservation/public_key.pem |
| AUTHORIZATION_SECRET_ARN | Authorization 대칭키(HS256) Secrets Manager ARN (authorizer) | arn:aws:secretsmanager:...:dev-authorization-secret |
| RESERVATION_AUDIENCE | 예약 토큰 aud 검증값 (authorizer, 기본 `reservation_waiting`) | reservation_waiting |
| USER_CLAIM | 동일 유저 판별 클레임 이름 (authorizer, 기본 `user_id`) | user_id |

> authorizer 의 키 위치는 모두 infra(terraform)에서 주입한다. S3 공개키는 `s3:GetObject`,
> Secrets Manager 대칭키는 `secretsmanager:GetSecretValue` 권한이 Lambda 실행 역할에 필요하다.

## Layer
| 레이어명 | 설명 | 런타임 |
|----------|------|--------|
| redis-layer | redis 라이브러리 | Python 3.12 |
| psycopg2-layer | psycopg2 라이브러리 (persistence) | Python 3.12 |
| jwt-layer | PyJWT + cryptography 라이브러리 (RS256/HS256 검증, authorizer·ticketing) | Python 3.12 |
| secrets-extension | AWS Parameters and Secrets Lambda Extension (Authorization 대칭키 로컬 캐시, authorizer) | AWS 관리형 Layer |

# Convention
팀 내 협업의 효율 및 생산성을 위한 규약

## Github 컨벤션

### Issue
**템플릿을 준수**
이슈 타이틀 형태: `[카테고리]: 이슈 제목`

카테고리
- Feature: 기능 추가, 기능 변경
- Refactor: 리팩토링, 구조 변경
- Bug: 발생한 버그 목록
- Chore: 의존성, 문서 작업 등 코드 외 작업 (별도의 의존성 작업만 추가할 경우)

EX
`[Feature] OAuth 2.0 추가`
`[Refactor] Ansible 모듈 리팩토링`

### Branch
브랜치 이름 형태: `카테고리/#이슈번호/브랜치명`

카테고리
- feature: 기능 추가, 기능 변경
- refactor: 리팩토링, 구조 변경
- fix: 버그 수정
- chore: 의존성, 문서 작업 등 코드 외 작업 (별도의 의존성 작업만 추가할 경우)

### Commit
커밋 메시지 형태: `[카테고리]: 커밋 내용`

카테고리
- FEAT: 기능 추가, 기능 변경
- REFAC: 리팩토링, 구조 변경
- FIX: 버그 수정, 오류 수정
- CHORE: 의존성 추가, 코드 외 작업

EX
`[FEAT]: OAuth2.0 추가 - Google, Naver Authentication`
`[CHORE]: pytest 의존성 추가`

### Pull Request
**템플릿을 준수**

제목 형태: `[카테고리#이슈번호] PR 제목`

카테고리
- FEAT: 기능 추가, 기능 변경
- REFAC: 리팩토링, 구조 변경
- FIX: 버그 수정, 오류 수정
- CHORE: 의존성 추가, 코드 외 작업
**카테고리는 커밋과 동일**

EX
`[FEAT#18] Google, Naver OAuth 2.0 추가`

## Code 컨벤션

### Naming

**Class**
클래스는 PascalCase로 작성

기본 작성 규칙
- 각 클래스는 명명된 모델 및 엔티티에 맞춰 작성
- 객체 지향 원칙에 따른 엔티티 작성
- 필요한 경우 인터페이스를 위한 추상 클래스 작성 후 상속

EX
`class User`
`class Payment`

**Method**
메소드는 camelCase로 작성

기본 작성 규칙
- public 메소드는 일반문자로 시작
- private 메소드는 언더바(_) 로 시작
- parameter는 최대한 엔티티 요소를 함축한 단어로 작성
- Restful API 키워드보다는 메소드의 동작 방식을 기준으로 명명

EX
`def getUser()`
`def createUser()`

**Variable**
변수는 snake_case로 작성

기본 작성 규칙
- 각 변수는 사용처, 알고리즘, 아키텍처에 맞는 명칭 사용
- 의미 없는 변수 (ex: data1, document 등) 사용 금지
- 속성 변수는 외부에서 최대한 사용하지 않도록 배제 (의존성 감소를 위한 규칙)

EX
`user = User()`

### Architecture
기본은 DDD 아키텍처에 기반한 설계
모듈형으로 설계

아키텍처 일반화
- common: 공용 모듈
- domains: 각 서비스 도메인 별 모듈
