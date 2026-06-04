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
├── domains/
│   └── ticketing/
│       └── issue_ticket.py
├── common/
└── README.md
```

## Lambda Functions

### issue_ticket (domains/ticketing)
| 항목 | 내용 |
|------|------|
| 역할 | 대기열 순번 발급 및 앞 순번 조회 |
| 입력 | event_id, user_id |
| 출력 | message, queue_number, remaining |
| 특이사항 | 동일 user_id 재요청 시 기존 번호 반환 |

## Environment Variables
| 변수명 | 설명 | 예시 |
|--------|------|------|
| REDIS_HOST | ElastiCache 엔드포인트 주소 | xxx.cache.amazonaws.com |
| REDIS_PORT | Redis 포트 | 6379 |
| EKS_ENDPOINT | EKS 서비스 엔드포인트 | http://eks-endpoint |

## Layer
| 레이어명 | 설명 | 런타임 |
|----------|------|--------|
| redis-layer | redis 라이브러리 | Python 3.12 |

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
