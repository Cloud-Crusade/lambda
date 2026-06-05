"""RDS#2(reservation/payment) 멱등 적재 — psycopg2 커넥션을 재사용한다."""
import os
from typing import Any

import psycopg2

DB_URL = os.environ.get("RESERVATION_DB_URL", "")


class ReservationRepository:
    def __init__(self, db_url: str = DB_URL) -> None:
        self._db_url = db_url
        self._connection = None

    def _getConnection(self) -> Any:
        if self._connection is None or self._connection.closed:
            self._connection = psycopg2.connect(self._db_url)
        return self._connection

    def commit(self) -> None:
        if self._connection is not None:
            self._connection.commit()

    def rollback(self) -> None:
        if self._connection is not None:
            self._connection.rollback()

    def reset(self) -> None:
        # OperationalError(RDS 페일오버 등) 후 커넥션 폐기 → 다음 호출에서 재연결
        if self._connection is not None:
            try:
                self._connection.close()
            finally:
                self._connection = None

    def insertReservation(self, message: dict[str, Any]) -> None:
        with self._getConnection().cursor() as cur:
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

    def cancelReservation(self, message: dict[str, Any]) -> None:
        with self._getConnection().cursor() as cur:
            cur.execute(
                "UPDATE reservations SET is_canceled = true, last_modified = CURRENT_DATE "
                "WHERE reservation_id = %s",
                (message["reservation_id"],),
            )

    def insertPayment(self, message: dict[str, Any]) -> None:
        with self._getConnection().cursor() as cur:
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
