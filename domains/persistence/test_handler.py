"""leaky bucket 핸들러의 순수 로직(그룹 분리·부분 실패·action 분기) 단위 테스트.

DB 드라이버(psycopg2) 없이 돌도록 import 전에 psycopg2 를 스텁한다.
실행: python -m unittest domains/persistence/test_handler.py
"""
import json
import sys
import types
import unittest
from unittest import mock

# psycopg2 미설치 환경에서도 import 되도록 스텁 주입 (OperationalError 만 사용)
if "psycopg2" not in sys.modules:
    stub = types.ModuleType("psycopg2")
    stub.OperationalError = type("OperationalError", (Exception,), {})
    stub.connect = lambda *a, **k: None
    sys.modules["psycopg2"] = stub

from domains.persistence import handler  # noqa: E402


def _record(message_id: str, group_id: str, body: dict) -> dict:
    return {
        "messageId": message_id,
        "attributes": {"MessageGroupId": group_id},
        "body": json.dumps(body),
    }


class _FakeCursor:
    def __init__(self, calls: list) -> None:
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql: str, params: tuple) -> None:
        self._calls.append((sql, params))


class _FakeConn:
    def __init__(self) -> None:
        self.calls: list = []
        self.closed = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.calls)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


class LeakyBucketHandlerTest(unittest.TestCase):
    def test_all_records_succeed_returns_no_failures(self):
        event = {"Records": [_record("m1", "g1", {"action": "reservation.create"})]}

        with mock.patch.object(handler, "_processRecord"), mock.patch.object(
            handler, "_getConnection", return_value=_FakeConn(),
        ):
            result = handler.lambda_handler(event, None)

        self.assertEqual(result["batchItemFailures"], [])

    def test_failure_reports_failed_and_remaining_in_same_group(self):
        event = {
            "Records": [
                _record("m1", "g1", {}),
                _record("m2", "g1", {}),  # 여기서 실패
                _record("m3", "g1", {}),
                _record("m4", "g2", {}),  # 다른 그룹 → 영향 없음
            ],
        }

        def fake_process(conn, record):
            if record["messageId"] == "m2":
                raise ValueError("boom")

        with mock.patch.object(
            handler, "_processRecord", side_effect=fake_process,
        ), mock.patch.object(handler, "_getConnection", return_value=_FakeConn()):
            result = handler.lambda_handler(event, None)

        failed_ids = {f["itemIdentifier"] for f in result["batchItemFailures"]}
        # m2(실패) 와 m3(이후, 순서 유지)만 재처리, m1·m4 는 제외
        self.assertEqual(failed_ids, {"m2", "m3"})

    def test_operational_error_drops_connection(self):
        handler._connection = object()
        event = {"Records": [_record("m1", "g1", {})]}

        with mock.patch.object(
            handler, "_processRecord", side_effect=handler.OperationalError("down"),
        ), mock.patch.object(handler, "_getConnection", return_value=_FakeConn()):
            result = handler.lambda_handler(event, None)

        self.assertEqual(
            [f["itemIdentifier"] for f in result["batchItemFailures"]], ["m1"],
        )
        self.assertIsNone(handler._connection)

    def test_process_record_routes_by_action(self):
        conn = _FakeConn()

        handler._processRecord(conn, _record("m1", "g1", {
            "action": "reservation.create",
            "reservation_id": "r1", "user_id": "u1", "event_id": "e1", "reserved_num": 3,
        }))
        handler._processRecord(conn, _record("m2", "g1", {
            "action": "payment.create",
            "payment_history_id": "p1", "user_id": "u1",
            "reservation_id": "r1", "payment_method": "mock",
        }))

        tables = " ".join(sql for sql, _ in conn.calls)
        self.assertIn("INSERT INTO reservations", tables)
        self.assertIn("INSERT INTO payment_histories", tables)

    def test_process_record_unknown_action_raises(self):
        conn = _FakeConn()
        with self.assertRaises(ValueError):
            handler._processRecord(conn, _record("m1", "g1", {"action": "bogus"}))


if __name__ == "__main__":
    unittest.main()
