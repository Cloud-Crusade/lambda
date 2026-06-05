"""PersistenceConsumer 의 순수 로직(그룹 분리·부분 실패·action 분기) 단위 테스트.

DB 드라이버(psycopg2) 없이 돌도록 import 전에 psycopg2 를 스텁한다.
실행: python -m unittest test/domains/persistence/test_consumer.py
"""
import json
import sys
import types
import unittest

# psycopg2 미설치 환경에서도 import 되도록 스텁 주입 (OperationalError 만 사용)
if "psycopg2" not in sys.modules:
    stub = types.ModuleType("psycopg2")
    stub.OperationalError = type("OperationalError", (Exception,), {})
    stub.connect = lambda *a, **k: None
    sys.modules["psycopg2"] = stub

from psycopg2 import OperationalError  # noqa: E402

from domains.persistence.consumer import PersistenceConsumer  # noqa: E402


def _record(message_id: str, group_id: str, body: dict) -> dict:
    return {
        "messageId": message_id,
        "attributes": {"MessageGroupId": group_id},
        "body": json.dumps(body),
    }


class _FakeRepository:
    """consume 로직 검증용 — message 의 마커(_fail/_op)로 실패를 모사한다."""

    def __init__(self) -> None:
        self.calls: list = []
        self.commits = 0
        self.rollbacks = 0
        self.resets = 0

    def _check(self, message: dict) -> None:
        if message.get("_op"):
            raise OperationalError("down")
        if message.get("_fail"):
            raise ValueError("boom")

    def insertReservation(self, message: dict) -> None:
        self._check(message)
        self.calls.append(("reservation", message))

    def cancelReservation(self, message: dict) -> None:
        self._check(message)
        self.calls.append(("cancel", message))

    def insertPayment(self, message: dict) -> None:
        self._check(message)
        self.calls.append(("payment", message))

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def reset(self) -> None:
        self.resets += 1


def _consumer() -> tuple[PersistenceConsumer, _FakeRepository]:
    repo = _FakeRepository()
    return PersistenceConsumer(repository=repo), repo


def _createBody(**extra: object) -> dict:
    return {"action": "reservation.create", "reservation_id": "r1", **extra}


class PersistenceConsumerTest(unittest.TestCase):
    def test_all_records_succeed_returns_no_failures(self):
        consumer, repo = _consumer()
        event = {"Records": [_record("m1", "g1", _createBody())]}

        result = consumer.consume(event)

        self.assertEqual(result["batchItemFailures"], [])
        self.assertEqual(repo.commits, 1)

    def test_failure_reports_failed_and_remaining_in_same_group(self):
        consumer, _ = _consumer()
        event = {
            "Records": [
                _record("m1", "g1", _createBody()),
                _record("m2", "g1", _createBody(_fail=True)),  # 실패
                _record("m3", "g1", _createBody()),
                _record("m4", "g2", _createBody()),  # 다른 그룹 → 영향 없음
            ],
        }

        result = consumer.consume(event)

        failed_ids = {f["itemIdentifier"] for f in result["batchItemFailures"]}
        self.assertEqual(failed_ids, {"m2", "m3"})

    def test_operational_error_resets_repository(self):
        consumer, repo = _consumer()
        event = {"Records": [_record("m1", "g1", _createBody(_op=True))]}

        result = consumer.consume(event)

        self.assertEqual(
            [f["itemIdentifier"] for f in result["batchItemFailures"]], ["m1"],
        )
        self.assertEqual(repo.resets, 1)

    def test_routes_by_action(self):
        consumer, repo = _consumer()
        event = {
            "Records": [
                _record("m1", "g1", {
                    "action": "reservation.create", "reservation_id": "r1",
                }),
                _record("m2", "g1", {
                    "action": "payment.create", "payment_history_id": "p1",
                }),
                _record("m3", "g1", {
                    "action": "reservation.cancel", "reservation_id": "r1",
                }),
            ],
        }

        consumer.consume(event)

        kinds = [kind for kind, _ in repo.calls]
        self.assertEqual(kinds, ["reservation", "payment", "cancel"])

    def test_unknown_action_reported_as_failure(self):
        consumer, _ = _consumer()
        event = {"Records": [_record("m1", "g1", {"action": "bogus"})]}

        result = consumer.consume(event)

        self.assertEqual(
            [f["itemIdentifier"] for f in result["batchItemFailures"]], ["m1"],
        )


if __name__ == "__main__":
    unittest.main()
