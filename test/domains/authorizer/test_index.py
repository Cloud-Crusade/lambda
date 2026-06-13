"""authorizer 핸들러 — Allow 정책 Resource 가 메서드/경로 와일드카드인지 검증.

실행: python -m unittest test/domains/authorizer/test_index.py
"""
import sys
import types
import unittest
from unittest import mock

# 다른 테스트 스텁과 공존하도록 jwt 모듈만 보장(service 가 import)
sys.modules.setdefault("jwt", types.ModuleType("jwt"))

from domains.authorizer import index as index_module  # noqa: E402


class WildcardResourceTest(unittest.TestCase):
    def test_wildcard_strips_method_and_path(self):
        arn = "arn:aws:execute-api:ap-northeast-2:123456789012:abc123/prod/GET/reservations/1"
        self.assertEqual(
            index_module._wildcardResource(arn),
            "arn:aws:execute-api:ap-northeast-2:123456789012:abc123/prod/*",
        )

    def test_allow_policy_resource_is_wildcard(self):
        # 캐시된 정책이 다른 메서드(DELETE 등)에도 적용되도록 Allow Resource 는 와일드카드여야 함
        arn = "arn:aws:execute-api:r:a:api/stage/DELETE/reservations/1"
        with mock.patch.object(index_module._service, "authorize", return_value="u1"):
            res = index_module.lambda_handler({"methodArn": arn, "headers": {}}, None)

        stmt = res["policyDocument"]["Statement"][0]
        self.assertEqual(stmt["Effect"], "Allow")
        self.assertEqual(stmt["Resource"], "arn:aws:execute-api:r:a:api/stage/*")
        self.assertEqual(res["context"]["user_id"], "u1")


if __name__ == "__main__":
    unittest.main()
