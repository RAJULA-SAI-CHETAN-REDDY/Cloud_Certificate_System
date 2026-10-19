"""Read-only local certificate verification; storage can later move to DynamoDB."""

import json
import hmac
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
try:
    from .organizations import record_organization, organization_name
except ImportError:
    from organizations import record_organization, organization_name

ID_PATTERN = re.compile(r"CERT-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
PUBLIC_FIELDS = ("certificate_id", "recipient_name", "course_name", "organization",
                 "issue_date", "expiry_date")
INDIA_TIME = timezone(timedelta(hours=5, minutes=30))


def verify_certificate(certificate_id, records_dir, today=None):
    if not ID_PATTERN.fullmatch(certificate_id):
        raise ValueError("Enter a certificate ID in the format shown on your certificate.")
    path = Path(records_dir) / f"{certificate_id}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"status": "NOT_FOUND"}
    return public_result(record, certificate_id, today)


def public_result(record, certificate_id, today=None, candidate_sha256=None):
    """Apply the same status and privacy rules to local and DynamoDB records."""
    if not isinstance(record, dict) or record.get("certificate_id") != certificate_id:
        raise RuntimeError("Invalid certificate record")
    if any(not isinstance(record.get(field), str) for field in PUBLIC_FIELDS):
        raise RuntimeError("Incomplete certificate record")
    if record.get("status") not in ("ACTIVE", "REVOKED"):
        raise RuntimeError("Unknown stored certificate status")
    issued = date.fromisoformat(record["issue_date"])
    expires = date.fromisoformat(record["expiry_date"])
    if expires < issued:
        raise RuntimeError("Invalid certificate dates")
    today = today or datetime.now(INDIA_TIME).date()
    if record["status"] == "REVOKED":
        status = "REVOKED"
    elif today > expires:
        status = "EXPIRED"
    elif today < issued:
        status = "NOT_YET_VALID"
    else:
        status = "ACTIVE"
    result = {**{field: record[field] for field in PUBLIC_FIELDS}, "status": status}
    organization = record_organization(record)
    if organization:
        result["organization"] = organization_name(organization)
    if candidate_sha256 is not None:
        stored = record.get("pdf_sha256")
        result["pdf_match"] = hmac.compare_digest(stored, candidate_sha256) if isinstance(stored, str) and re.fullmatch(r"[0-9a-f]{64}", stored) else None
    return result
