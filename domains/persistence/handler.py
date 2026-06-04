"""예약·결제 FIFO 큐를 leaky bucket 으로 소비해 RDS#2 에 적재하는 Lambda.

- batchSize 10 으로 수신하고, 예약 동시성(reserved concurrency) 5~10 으로 제한해
  DB 유입 속도를 일정하게 흘려보낸다(leaky bucket). 두 값은 이벤트 소스 매핑/함수
  설정값이며 infra(terraform modules/sqs_lambda)에서 지정한다.
- FIFO 큐이므로 messageGroupId 단위로 순서가 보장된다. 그룹 내 첫 실패부터 끝까지는
  순서 유지를 위해 처리하지 않고 batchItemFailures 로 돌려 SQS 가 재처리하게 한다.
- 메시지 계약은 app repo 의 reservation/payment messages.py 와 공유한다.
"""
import json
import logging
import os
from collections import defaultdict
from typing import Any

import psycopg2
from psycopg2 import OperationalError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DB_URL = os.environ.get("RESERVATION_DB_URL", "")

_connection = None


def _getConnection():
    global _connection
    if _connection is None or _connection.closed:
        _connection = psycopg2.connect(DB_URL)
    return _connection


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    # FIFO: messageGroupId 별로 묶어 그룹 내 순차 처리, 그룹 간은 독립
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in event.get("Records", []):
        group_id = record.get("attributes", {}).get("MessageGroupId", "")
        groups[group_id].append(record)

    failures: list[dict[str, str]] = []
    for group_records in groups.values():
        failed_from = _processGroup(group_records)
        if failed_from is not None:
            # 첫 실패 메시지부터 그룹 끝까지는 순서 유지를 위해 재처리 대상으로 표시
            failures.extend(
                {"itemIdentifier": record["messageId"]}
                for record in group_records[failed_from:]
            )

    return {"batchItemFailures": failures}


def _processGroup(group_records: list[dict[str, Any]]) -> int | None:
    global _connection
    try:
        conn = _getConnection()
    except OperationalError:
        logger.exception("db_connect_failed")
        _connection = None
        return 0

    for index, record in enumerate(group_records):
        try:
            _processRecord(conn, record)
            conn.commit()
        except OperationalError:
            # RDS 페일오버 등 일시 오류 → 커넥션 폐기 후 SQS 재처리에 위임
            logger.exception("db_operational_error: message_id=%s", record.get("messageId"))
            _connection = None
            return index
        except Exception:
            conn.rollback()
            logger.exception("record_process_failed: message_id=%s", record.get("messageId"))
            return index

    return None


def _processRecord(conn: Any, record: dict[str, Any]) -> None:
    message = json.loads(record["body"])
    action = message.get("action")
    if action == "reservation.create":
        _insertReservation(conn, message)
    elif action == "reservation.cancel":
        _cancelReservation(conn, message)
    elif action == "payment.create":
        _insertPayment(conn, message)
    else:
        # 알 수 없는 action 은 재처리해도 동일 실패 → DLQ 로 격리되도록 raise
        raise ValueError(f"unknown action: {action}")


def _insertReservation(conn: Any, message: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO reservations (reservation_id, user_id, event_id, reserved_num) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (reservation_id) DO NOTHING",
            (
                message["reservation_id"],
                message["user_id"],
                message["event_id"],
                message["reserved_num"],
            ),
        )
    logger.info("reservation_created: reservation_id=%s", message["reservation_id"])


def _cancelReservation(conn: Any, message: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE reservations SET is_canceled = true, last_modified = CURRENT_DATE "
            "WHERE reservation_id = %s",
            (message["reservation_id"],),
        )
    logger.info("reservation_canceled: reservation_id=%s", message["reservation_id"])


def _insertPayment(conn: Any, message: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO payment_histories "
            "(payment_history_id, user_id, reservation_id, payment_method) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (payment_history_id) DO NOTHING",
            (
                message["payment_history_id"],
                message["user_id"],
                message["reservation_id"],
                message["payment_method"],
            ),
        )
    logger.info("payment_created: payment_history_id=%s", message["payment_history_id"])
