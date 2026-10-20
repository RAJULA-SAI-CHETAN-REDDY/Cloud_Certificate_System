"""Lambda handler for API Gateway GET /verify/{id}."""

import json
import logging
import os

import boto3

from verification import ID_PATTERN, public_result
from admin_auth import allow_admin_origin, session as admin_session

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
_table = None
_s3 = None


def response(code, body):
    return {
        "statusCode": code,
        # This endpoint exposes only public verification data, with no cookies or login.
        # Administrator endpoints must use their own authentication and CORS rules.
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def download_response(record, certificate_id):
    """Redirect to a five-minute private PDF download for a current record."""
    global _s3
    bucket = os.environ["CERTIFICATE_BUCKET"]
    key = f"certificates/{certificate_id}.pdf"
    if record.get("retired_at") or record.get("s3_bucket") != bucket or record.get("s3_key") != key:
        return response(404, {"error": "Certificate PDF is unavailable."})
    if _s3 is None:
        _s3 = boto3.client("s3")
    url = _s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key,
        "ResponseContentDisposition": f'attachment; filename="{certificate_id}.pdf"'}, ExpiresIn=300)
    return {"statusCode": 302, "headers": {"Location": url, "Cache-Control": "no-store"}, "body": ""}


def lambda_handler(event, context):
    global _table
    if str(event.get("resource", "")).startswith("/admin"):
        return allow_admin_origin(admin_session(event), event)
    certificate_id = (event.get("pathParameters") or {}).get("id", "")
    query = event.get("queryStringParameters") or {}
    candidate_sha256 = query.get("sha256")
    if not isinstance(certificate_id, str) or not ID_PATTERN.fullmatch(certificate_id):
        return response(400, {"error": "Enter the full certificate ID printed on your certificate."})
    if candidate_sha256 is not None and (not isinstance(candidate_sha256, str) or len(candidate_sha256) != 64 or any(c not in "0123456789abcdef" for c in candidate_sha256)):
        return response(400, {"error": "Invalid PDF fingerprint."})
    try:
        if _table is None:
            _table = boto3.resource("dynamodb").Table(os.environ["CERTIFICATE_TABLE"])
        record = _table.get_item(
            Key={"certificate_id": certificate_id}, ConsistentRead=True
        ).get("Item")
        if record is None:
            return response(404, {"status": "NOT_FOUND"})
        result = public_result(record, certificate_id, candidate_sha256=candidate_sha256)
        if query.get("download") == "1":
            return download_response(record, certificate_id)
        return response(200, result)
    except Exception as error:
        # No event, record, certificate ID, or exception message in public logs.
        logger.error("Verification failed: type=%s request=%s", type(error).__name__,
                     getattr(context, "aws_request_id", "unknown"))
        return response(500, {"error": "Verification is temporarily unavailable. Please try again."})
