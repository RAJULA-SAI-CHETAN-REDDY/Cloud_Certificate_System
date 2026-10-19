"""Local development server. Run from the project root; not for production hosting."""

import argparse
import json
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

try:
    from .verification import ID_PATTERN, public_result, verify_certificate
except ImportError:
    from verification import ID_PATTERN, public_result, verify_certificate

ROOT = Path(__file__).resolve().parents[1]
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/css/navigation.css": ("css/navigation.css", "text/css; charset=utf-8"),
    "/verify.html": ("verify.html", "text/html; charset=utf-8"),
    "/css/verify.css": ("css/verify.css", "text/css; charset=utf-8"),
    "/js/verify.js": ("js/verify.js", "text/javascript; charset=utf-8"),
    "/js/scan.js": ("js/scan.js", "text/javascript; charset=utf-8"),
    "/js/pdf.worker.min.mjs": ("js/pdf.worker.min.mjs", "text/javascript; charset=utf-8"),
    "/js/config.js": ("js/config.js", "text/javascript; charset=utf-8"),
    "/admin.html": ("admin.html", "text/html; charset=utf-8"),
    "/css/admin.css": ("css/admin.css", "text/css; charset=utf-8"),
    "/js/admin-config.js": ("js/admin-config.js", "text/javascript; charset=utf-8"),
    "/js/admin.js": ("js/admin.js", "text/javascript; charset=utf-8"),
}


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, records_dir, **kwargs):
        self.records_dir = records_dir
        super().__init__(*args, **kwargs)

    def send_body(self, code, body, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self' https://v8wddxhk67.execute-api.ap-south-1.amazonaws.com https://ccd-admin-707256068320.auth.ap-south-1.amazoncognito.com https://cognito-idp.ap-south-1.amazonaws.com; worker-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code, data):
        self.send_body(code, json.dumps(data).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        url = urlsplit(self.path)
        path = unquote(url.path)
        if path.startswith("/api/verify/"):
            certificate_id = path[len("/api/verify/"):]
            if not ID_PATTERN.fullmatch(certificate_id):
                self.send_json(400, {"error": "Enter the full certificate ID printed on your certificate."})
                return
            try:
                result = verify_certificate(certificate_id, self.records_dir)
                candidate = parse_qs(url.query).get("sha256", [None])[0]
                if candidate is not None and (len(candidate) != 64 or any(c not in "0123456789abcdef" for c in candidate)):
                    self.send_json(400, {"error": "Invalid PDF fingerprint."})
                    return
                record_path = self.records_dir / f"{certificate_id}.json"
                if not record_path.exists() and self.records_dir == ROOT / "output" / "pdf":
                    record_path = ROOT / "output" / "generic-samples" / f"{certificate_id}.json"
                if record_path.exists() and (candidate is not None or result["status"] == "NOT_FOUND"):
                    result = public_result(json.loads(record_path.read_text(encoding="utf-8")), certificate_id, candidate_sha256=candidate)
            except (ValueError, RuntimeError, OSError, KeyError, TypeError):
                self.send_json(500, {"error": "Verification is temporarily unavailable. Please try again."})
                return
            self.send_json(404 if result["status"] == "NOT_FOUND" else 200, result)
        elif path in ASSETS:
            filename, content_type = ASSETS[path]
            self.send_body(200, (ROOT / "frontend" / filename).read_bytes(), content_type)
        else:
            self.send_json(404, {"error": "Page not found."})

    def log_message(self, format, *args):
        # Avoid writing certificate identifiers or personal details into logs.
        pass


def make_server(port=8000, records_dir=ROOT / "output" / "pdf"):
    return ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, records_dir=records_dir))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--records-dir", type=Path, default=ROOT / "output" / "pdf")
    args = parser.parse_args()
    with make_server(args.port, args.records_dir) as server:
        print(f"Open http://localhost:{args.port}/", flush=True)
        print("Local development only. Press Ctrl+C to stop.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
