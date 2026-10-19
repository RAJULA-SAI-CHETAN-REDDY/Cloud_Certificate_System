import copy
import hashlib
import io
import json
import os
import unittest
from unittest.mock import patch

from botocore.exceptions import ClientError
from backend import lambda_issue

DATA = {"recipient_name": "Example Recipient", "course_name": "Cloud Computing",
        "organization": "Organization 1", "issue_date": "2026-10-10", "expiry_date": "2027-10-10"}
REQUEST = "12345678-1234-4234-8234-123456789abc"


def error(code):
    return ClientError({"Error": {"Code": code, "Message": "private details"}}, "Test")


class Table:
    def __init__(self):
        self.items = {}
        self.fail_certificate = False
        self.lose_reservation_response = False

    def get_item(self, Key, **kwargs):
        return {"Item": copy.deepcopy(self.items[Key["certificate_id"]])} if Key["certificate_id"] in self.items else {}

    def put_item(self, Item, **kwargs):
        key = Item["certificate_id"]
        if key in self.items:
            raise error("ConditionalCheckFailedException")
        if self.fail_certificate and key.startswith("CERT-"):
            self.fail_certificate = False
            raise RuntimeError("private database failure")
        self.items[key] = copy.deepcopy(Item)
        if self.lose_reservation_response and key.startswith("ISSUE#"):
            self.lose_reservation_response = False
            raise RuntimeError("lost write response")


class S3:
    def __init__(self):
        self.objects = {}
        self.fail = False

    def put_object(self, **kwargs):
        if self.fail:
            self.fail = False
            raise RuntimeError("private storage failure")
        if kwargs["Key"] in self.objects:
            raise error("PreconditionFailed")
        assert kwargs["IfNoneMatch"] == "*"
        assert kwargs["ServerSideEncryption"] == "AES256"
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, **kwargs):
        return {"Body": io.BytesIO(self.objects[kwargs["Key"]])}

    def generate_presigned_url(self, operation, **kwargs):
        assert kwargs["ExpiresIn"] == 300
        return "https://example.test/private-download"


class IssuanceTests(unittest.TestCase):
    def setUp(self):
        self.table, self.s3 = Table(), S3()
        env = patch.dict(os.environ, {"ADMIN_ORGANIZATIONS": json.dumps({"admin": "org-1"})})
        env.start()
        self.addCleanup(env.stop)

    def issue(self, data=None, request=REQUEST, subject="admin-user"):
        return lambda_issue.issue(DATA if data is None else data, request, subject, self.table, self.s3,
                                  "private-bucket", "http://localhost:8000/verify.html", "org-1")

    def test_pdf_hash_storage_and_idempotent_retry(self):
        first = self.issue()
        second = self.issue()
        self.assertEqual(first, second)
        self.assertEqual(len(self.s3.objects), 1)
        self.assertEqual(len(self.table.items), 2)
        pdf = next(iter(self.s3.objects.values()))
        record = self.table.items[first["certificate_id"]]
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertEqual(record["pdf_sha256"], hashlib.sha256(pdf).hexdigest())
        self.assertEqual(record["status"], "ACTIVE")
        self.assertIn(first["certificate_id"], first["verification_url"])
        self.assertNotIn("pdf_sha256", first)

    def test_request_key_binding_and_subject_isolation(self):
        first = self.issue()
        with self.assertRaises(lambda_issue.Conflict):
            self.issue({**DATA, "recipient_name": "Different Recipient"})
        self.assertEqual(len(self.s3.objects), 1)
        self.assertNotEqual(first["certificate_id"], self.issue(subject="other-admin")["certificate_id"])

    def test_retry_after_s3_and_database_partial_failures(self):
        self.s3.fail = True
        with self.assertRaises(RuntimeError):
            self.issue()
        self.assertFalse(any(key.startswith("CERT-") for key in self.table.items))
        self.table.fail_certificate = True
        with self.assertRaises(RuntimeError):
            self.issue()
        self.assertEqual(len(self.s3.objects), 1)
        result = self.issue()
        self.assertIn(result["certificate_id"], self.table.items)
        self.assertEqual(len(self.s3.objects), 1)

    def test_lost_reservation_response_and_existing_pdf_mismatch(self):
        self.table.lose_reservation_response = True
        self.issue()
        key = next(iter(self.s3.objects))
        self.s3.objects[key] = b"different PDF"
        with self.assertRaises(lambda_issue.Conflict):
            self.issue()
        self.assertEqual(self.s3.objects[key], b"different PDF")

    def test_validation_has_no_storage_writes(self):
        invalid = [None, [], {**DATA, "extra": "value"}, {**DATA, "recipient_name": " "},
                   {**DATA, "recipient_name": 1}, {**DATA, "expiry_date": "2020-01-01"},
                   {**DATA, "recipient_name": "\u00e9"}, {**DATA, "course_name": "x" * 121}]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                lambda_issue.issue(data, REQUEST, "admin", self.table, self.s3, "bucket", "http://localhost:8000/verify.html", "org-1")
        with self.assertRaises(ValueError):
            self.issue(request="not-a-uuid")
        self.assertEqual(self.table.items, {})
        self.assertEqual(self.s3.objects, {})

    def test_authorization_precedes_storage_and_request_validation(self):
        with patch.object(lambda_issue, "_table", self.table), patch.object(lambda_issue, "_s3", self.s3):
            self.assertEqual(lambda_issue.lambda_handler({}, None)["statusCode"], 401)
        self.assertEqual(self.table.items, {})

    def test_handler_success_non_admin_and_generic_failure(self):
        env = {"ADMIN_ISSUER": "issuer", "ADMIN_CLIENT_ID": "client", "CERTIFICATE_TABLE": "table",
               "CERTIFICATE_BUCKET": "bucket", "VERIFICATION_BASE_URL": "http://localhost:8000/verify.html"}
        event = {"resource": "/admin/certificates", "httpMethod": "POST", "body": json.dumps(DATA),
                 "headers": {"Content-Type": "application/json", "Idempotency-Key": REQUEST},
                 "requestContext": {"authorizer": {"claims": {"iss": "issuer", "aud": "client", "exp": "2000",
                     "sub": "admin", "token_use": "id", "cognito:groups": "admins"}}}}
        with patch.dict(os.environ, env), patch("backend.admin_auth.time.time", return_value=1000), \
             patch.object(lambda_issue, "_table", self.table), patch.object(lambda_issue, "_s3", self.s3):
            self.assertEqual(lambda_issue.lambda_handler(event, None)["statusCode"], 201)
            event["requestContext"]["authorizer"]["claims"]["cognito:groups"] = "users"
            self.assertEqual(lambda_issue.lambda_handler(event, None)["statusCode"], 403)
            event["requestContext"]["authorizer"]["claims"]["cognito:groups"] = "admins"
            event["headers"]["Idempotency-Key"] = "87654321-1234-4234-8234-123456789abc"
            self.s3.fail = True
            with self.assertLogs(lambda_issue.logger, level="ERROR") as captured:
                result = lambda_issue.lambda_handler(event, None)
            self.assertEqual(result["statusCode"], 503)
            self.assertNotIn("private storage failure", str(result) + str(captured.output))

    def test_notification_failure_preserves_issued_certificate_and_auth_boundaries(self):
        event = {"resource": "/admin/certificates", "httpMethod": "POST", "body": json.dumps(DATA),
                 "headers": {"Content-Type": "application/json", "Idempotency-Key": REQUEST},
                 "requestContext": {"authorizer": {"claims": {"sub": "admin"}}}}
        env = {"CERTIFICATE_BUCKET": "bucket", "VERIFICATION_BASE_URL": "http://localhost:8000/verify.html",
               "NOTIFICATION_TOPIC_ARN": "topic"}
        with patch.dict(os.environ, env), patch.object(lambda_issue, "authorize", return_value=None), \
             patch.object(lambda_issue, "_table", self.table), patch.object(lambda_issue, "_s3", self.s3), \
             patch.object(lambda_issue, "_sns", object()), \
             patch.object(lambda_issue, "publish_issuance", side_effect=RuntimeError("private SNS error")) as notify:
            with self.assertLogs(lambda_issue.logger, level="ERROR") as logs:
                response = lambda_issue.lambda_handler(event, None)
            body = json.loads(response["body"])
            self.assertEqual(response["statusCode"], 201)
            self.assertEqual(body["notification_status"], "pending")
            self.assertIn(body["certificate_id"], self.table.items)
            self.assertEqual(len(self.s3.objects), 1)
            self.assertNotIn("private SNS error", str(logs.output))
            notify.assert_called_once()
            notify.reset_mock()
            self.s3.fail = True
            event["headers"]["Idempotency-Key"] = "87654321-1234-4234-8234-123456789abc"
            with self.assertLogs(lambda_issue.logger, level="ERROR"):
                self.assertEqual(lambda_issue.lambda_handler(event, None)["statusCode"], 503)
            notify.assert_not_called()
            with patch.object(lambda_issue, "authorize", return_value={"statusCode": 403}):
                self.assertEqual(lambda_issue.lambda_handler(event, None)["statusCode"], 403)
            notify.assert_not_called()
