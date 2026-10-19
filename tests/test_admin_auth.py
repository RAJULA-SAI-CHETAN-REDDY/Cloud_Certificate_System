import copy
import json
import os
import unittest
from unittest.mock import patch

from backend import admin_auth


class AdminAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"ADMIN_ISSUER": "trusted-issuer", "ADMIN_CLIENT_ID": "trusted-client"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.clock = patch("backend.admin_auth.time.time", return_value=1000)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.claims = {"iss": "trusted-issuer", "aud": "trusted-client", "token_use": "id",
                       "sub": "user-id", "exp": "1100", "cognito:groups": "[admins]"}
        self.event = {"resource": "/admin/session", "httpMethod": "GET",
                      "requestContext": {"authorizer": {"claims": self.claims}}}

    def test_admin_and_rest_group_formats(self):
        for groups in ("[admins]", "[other,admins]", '["other","admins"]', ["admins"], "admins,other"):
            self.claims["cognito:groups"] = groups
            result = admin_auth.session(self.event)
            self.assertEqual(result["statusCode"], 200)
            self.assertEqual(json.loads(result["body"]), {"authorized": True, "role": "Administrator", "organization_id": None, "organization": None})
            self.assertNotIn("user-id", result["body"])

    def test_missing_authorizer_and_spoofed_headers_denied(self):
        for event in ({}, {"headers": {"Authorization": "fake-token", "cognito:groups": "admins"}},
                      {"requestContext": {"authorizer": {"claims": "admins"}}}):
            self.assertEqual(admin_auth.session(event)["statusCode"], 401)

    def test_invalid_identity_denied(self):
        for key, value in (("iss", "other"), ("aud", "other"), ("token_use", "access"),
                           ("sub", ""), ("exp", "1000"), ("exp", "invalid"), ("exp", None)):
            event = copy.deepcopy(self.event)
            event["requestContext"]["authorizer"]["claims"][key] = value
            self.assertEqual(admin_auth.session(event)["statusCode"], 401)
        with patch.dict(os.environ, {"ADMIN_CLIENT_ID": ""}):
            self.assertEqual(admin_auth.session(self.event)["statusCode"], 401)

    def test_rest_authorizer_formatted_expiry(self):
        self.claims["exp"] = "Thu Jan 01 00:18:20 UTC 1970"
        self.assertEqual(admin_auth.session(self.event)["statusCode"], 200)
        for expiry in ("Thu Jan 01 00:16:40 UTC 1970", "Thu Jan 01 00:15:00 UTC 1970",
                       "Thu Jan 01 00:18:20 IST 1970", "not a date", "NaN", "Infinity", True):
            self.claims["exp"] = expiry
            with self.subTest(expiry=expiry):
                self.assertEqual(admin_auth.session(self.event)["statusCode"], 401)

    def test_non_admin_and_partial_group_names_denied(self):
        for groups in (None, "superadmins", "admins-other", "[users]", [], {"admins": True}):
            self.claims["cognito:groups"] = groups
            self.assertEqual(admin_auth.session(self.event)["statusCode"], 403)

    def test_cors_is_exact_origin_and_errors_are_not_cached(self):
        for code in (200, 401, 403, 404):
            headers = admin_auth.response(code, {})["headers"]
            self.assertEqual(headers["Access-Control-Allow-Origin"], "http://localhost:8000")
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertNotIn("Access-Control-Allow-Credentials", headers)

    def test_unknown_management_routes_fail_closed(self):
        for resource, method in (("/admin/certificates", "GET"), ("/admin/session", "POST")):
            self.event.update(resource=resource, httpMethod=method)
            self.assertEqual(admin_auth.session(self.event)["statusCode"], 404)
