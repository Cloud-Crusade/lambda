# persistence (lambda 도메인)

## 개요

SQS **FIFO** 큐(예약/결제)를 소비해 **RDS#2**(reservation/payment)에 **멱등 적재**하는 leaky bucket consumer. `batchSize` + reserved concurrency 로 DB 유입 속도를 일정하게 흘려보냅니다. RDS 접근을 위해 **VPC-attached** 로 동작합니다(`RESERVATION_DB_URL`).

## 트리거 · 핸들러

- **트리거**: SQS FIFO 큐의 **이벤트 소스 매핑**(infra: `batchSize=10`, reserved concurrency 5~10). API Gateway 가 아닌 비동기 소비입니다.
- **핸들러**: `domains.persistence.index.lambda_handler` → 모듈 로드 시 생성한 `PersistenceConsumer.consume(event)` 위임.

| 파일 | 책임 |
|------|------|
| `index.py` | 모듈 로드 시 `PersistenceConsumer` 생성, `consume(event)` 위임 |
| `consumer.py` | `PersistenceConsumer` — 그룹화·순차 처리·부분 실패·action 분기 |
| `repository.py` | `ReservationRepository` — psycopg2 커넥션 재사용·멱등 SQL |

## 핵심 동작

- **FIFO 그룹화** — `Records` 를 `MessageGroupId` 별로 묶어 그룹 내 순차 처리, 그룹 간은 독립적으로 처리합니다.
- **순서 보존 부분 실패** — 그룹 내 **첫 실패 메시지부터 끝까지**를 `batchItemFailures` 로 반환해 FIFO 순서를 유지(앞 메시지를 건너뛰지 않음).
- **action 분기** — `reservation.create`(INSERT) / `reservation.cancel`(UPDATE) / `payment.create`(INSERT). 미지의 action 은 `raise` → 재처리해도 동일 실패이므로 DLQ 로 격리됩니다.
- **오류 처리** — `OperationalError`(RDS 페일오버 등 일시 오류)는 커넥션을 `reset()`(폐기) 후 해당 인덱스부터 SQS 재처리에 위임, 그 외 예외는 `rollback()` 후 실패 인덱스를 반환합니다.
- **멱등 적재** — INSERT 는 PK 기준 `ON CONFLICT DO NOTHING`(`reservation_id`/`payment_history_id`)으로 중복 메시지 재처리에 안전합니다. psycopg2 커넥션은 재사용(`closed` 면 재연결)합니다.

## 의존 (AWS 서비스 · env)

- **AWS**: SQS FIFO(이벤트 소스 매핑), RDS PostgreSQL(reservation/payment), VPC. (시크릿/Extension 미사용)
- **라이브러리**: `psycopg2-binary`(psycopg2-layer).

| 환경변수 | 설명 |
|----------|------|
| `RESERVATION_DB_URL` | RDS#2 PostgreSQL 접속 URL (VPC 내) |

> 메시지 계약은 app repo 의 `reservation/payment messages.py` 와 공유합니다. `batchSize`·reserved concurrency 가 DB 유입 속도(leaky bucket)를 결정하며 infra(terraform)에서 지정합니다.

---
⬆ [domains README로](../README.md)
