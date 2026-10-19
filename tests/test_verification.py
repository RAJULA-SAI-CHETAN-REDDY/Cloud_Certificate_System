import json
import hashlib
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen
from urllib.parse import quote

from backend.local_server import make_server
from backend.verification import verify_certificate

ID = "CERT-11111111-1111-4111-8111-111111111111"


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.record = dict(certificate_id=ID, recipient_name="Example Recipient",
                           course_name="Cloud Computing", organization="Example Institute",
                           issue_date="2026-01-01", expiry_date="2026-10-03", status="ACTIVE",
                           pdf_sha256="private-hash", revocation_reason="private-note")
        self.save()

    def save(self):
        (self.directory / f"{ID}.json").write_text(json.dumps(self.record))

    def test_expiry_boundary_and_public_fields(self):
        result = verify_certificate(ID, self.directory, date(2026, 10, 3))
        self.assertEqual(result["status"], "ACTIVE")
        self.assertNotIn("pdf_sha256", result)
        self.assertNotIn("revocation_reason", result)
        self.assertEqual(verify_certificate(ID, self.directory, date(2026, 10, 4))["status"], "EXPIRED")
        self.assertEqual(verify_certificate(ID, self.directory, date(2025, 12, 31))["status"], "NOT_YET_VALID")

    def test_revocation_overrides_expiry(self):
        self.record["status"] = "REVOKED"
        self.save()
        self.assertEqual(verify_certificate(ID, self.directory, date(2027, 1, 1))["status"], "REVOKED")

    def test_pdf_fingerprint_compares_without_exposing_stored_hash(self):
        fingerprint = hashlib.sha256(b"issued PDF").hexdigest()
        self.record["pdf_sha256"] = fingerprint
        self.save()
        server = make_server(0, self.directory)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}/api/verify/{ID}?sha256="
            for supplied, expected in ((fingerprint, True), ("0" * 64, False)):
                with urlopen(base + supplied) as response:
                    body = json.load(response)
                self.assertIs(body["pdf_match"], expected)
                self.assertNotIn("pdf_sha256", body)
            with self.assertRaises(HTTPError) as caught:
                urlopen(base + quote("invalid"))
            self.assertEqual(caught.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_missing_and_traversal(self):
        self.assertEqual(verify_certificate(ID.replace("11111111", "22222222", 1), self.directory)["status"], "NOT_FOUND")
        with self.assertRaises(ValueError):
            verify_certificate("../../README", self.directory)

    def test_http_routes_and_corrupt_records(self):
        server = make_server(0, self.directory)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            for path in ("/", "/index.html"):
                with urlopen(base + path) as response:
                    html = response.read()
                    self.assertIn(b'Administrator sign in', html)
                    self.assertIn(b'href="./verify.html"', html)
            with urlopen(base + "/css/navigation.css") as response:
                self.assertEqual(response.status, 200)
            with urlopen(base + "/verify.html") as response:
                self.assertIn(b"Certificate ID", response.read())
            with urlopen(base + "/admin.html") as response:
                self.assertIn(b"Administrator access", response.read())
                self.assertIn("https://cognito-idp.ap-south-1.amazonaws.com", response.headers["Content-Security-Policy"])
                self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
            with urlopen(base + "/js/admin.js") as response:
                self.assertEqual(response.headers["Cache-Control"], "no-store")
            with urlopen(base + "/api/verify/" + ID) as response:
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertNotIn(b"private-hash", response.read())
            for path, code in [("/README.md", 404), ("/output/pdf/" + ID + ".json", 404),
                               ("/src/admin.js", 404), ("/node_modules/oidc-client-ts/package.json", 404),
                               ("/api/verify/..%2F..%2FREADME", 400),
                               ("/api/verify/" + ID.replace("11111111", "22222222", 1), 404)]:
                with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                    urlopen(base + path)
                self.assertEqual(caught.exception.code, code)
            (self.directory / f"{ID}.json").write_text("broken JSON")
            with self.assertRaises(HTTPError) as caught:
                urlopen(base + "/api/verify/" + ID)
            self.assertEqual(caught.exception.code, 500)
            self.assertNotIn(str(self.directory), caught.exception.read().decode())
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
