import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend import verification
from backend import admin_auth

with patch.dict(sys.modules, {"verification": verification, "admin_auth": admin_auth}):
    spec = importlib.util.spec_from_file_location("lambda_verify", Path(__file__).resolve().parents[1] / "backend/lambda_verify.py")
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)

ID = "CERT-11111111-1111-4111-8111-111111111111"


class LambdaVerificationTests(unittest.TestCase):
    def setUp(self):
        self.table = Mock()
        patcher = patch.object(handler, "_table", self.table)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.event = {"pathParameters": {"id": ID}}

    def test_invalid_id_does_not_read_database(self):
        self.assertEqual(handler.lambda_handler({}, None)["statusCode"], 400)
        self.table.get_item.assert_not_called()

    def test_admin_route_cannot_fall_through_to_public_lookup(self):
        result = handler.lambda_handler({"resource": "/admin/session", "pathParameters": {"id": ID},
            "headers": {"Origin": "http://localhost:8000"}}, None)
        self.assertEqual(result["statusCode"], 401)
        self.assertEqual(result["headers"]["Access-Control-Allow-Origin"], "http://localhost:8000")
        self.table.get_item.assert_not_called()

    def test_admin_cors_allows_cloud_site_only_when_configured(self):
        website = "https://d6uwrv2kb0dl8.cloudfront.net"
        with patch.dict(handler.os.environ, {"ADMIN_WEBSITE_ORIGIN": website}):
            for origin, expected in ((website, website), ("https://other.example", None)):
                result = handler.lambda_handler({"resource": "/admin/session",
                    "headers": {"origin": origin}}, None)
                self.assertEqual(result["headers"].get("Access-Control-Allow-Origin"), expected)

    def test_missing_record(self):
        self.table.get_item.return_value = {}
        self.assertEqual(handler.lambda_handler(self.event, None)["statusCode"], 404)

    def test_public_cors_on_success_and_errors(self):
        for code in (200, 400, 404, 500):
            result = handler.response(code, {})
            self.assertEqual(result["headers"]["Access-Control-Allow-Origin"], "*")
            self.assertNotIn("Access-Control-Allow-Credentials", result["headers"])
            self.assertEqual(result["headers"]["Cache-Control"], "no-store")

    def test_revocation_and_private_fields(self):
        self.table.get_item.return_value = {"Item": dict(
            certificate_id=ID, recipient_name="Example", course_name="Course",
            organization="Institute", issue_date="2020-01-01", expiry_date="2021-01-01",
            status="REVOKED", pdf_sha256="private", s3_key="private")}
        result = handler.lambda_handler(self.event, None)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(json.loads(result["body"])["status"], "REVOKED")
        self.assertNotIn("private", result["body"])
        self.table.get_item.assert_called_once_with(Key={"certificate_id": ID}, ConsistentRead=True)

    def test_database_failure_returns_generic_error(self):
        self.table.get_item.side_effect = RuntimeError("private database details")
        with self.assertLogs(handler.logger, level="ERROR") as captured:
            result = handler.lambda_handler(self.event, None)
        self.assertEqual(result["statusCode"], 500)
        self.assertNotIn("private database details", str(result) + str(captured.output))

    def test_uploaded_pdf_fingerprint_response(self):
        fingerprint = "a" * 64
        self.table.get_item.return_value = {"Item": dict(
            certificate_id=ID, recipient_name="Example", course_name="Course",
            organization="Organization 1", issue_date="2020-01-01", expiry_date="2027-01-01",
            status="ACTIVE", pdf_sha256=fingerprint)}
        event = {**self.event, "queryStringParameters": {"sha256": fingerprint}}
        body = json.loads(handler.lambda_handler(event, None)["body"])
        self.assertIs(body["pdf_match"], True)
        self.assertNotIn("pdf_sha256", body)
        event["queryStringParameters"] = {"sha256": "b" * 64}
        self.assertIs(json.loads(handler.lambda_handler(event, None)["body"])["pdf_match"], False)
        event["queryStringParameters"] = {"sha256": "invalid"}
        self.assertEqual(handler.lambda_handler(event, None)["statusCode"], 400)
