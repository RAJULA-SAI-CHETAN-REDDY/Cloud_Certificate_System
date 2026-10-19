"""Authenticated development certificate issuance with durable retry protection."""

import hashlib
import json
import logging
import os
from uuid import UUID, NAMESPACE_URL, uuid5

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

try:
    from .admin_auth import allow_admin_origin, authorize, response
    from .generate_certificate import generate_certificate
    from .notifications import publish_issuance
    from .management import handle as manage
    from .organizations import assigned_organization, organization_name
except ImportError:
    from admin_auth import allow_admin_origin, authorize, response
    from generate_certificate import generate_certificate
    from notifications import publish_issuance
    from management import handle as manage
    from organizations import assigned_organization, organization_name

logger = logging.getLogger(__name__)
_table = None
_s3 = None
_sns = None
FIELDS = ("recipient_name", "course_name", "organization", "issue_date", "expiry_date")


class Conflict(ValueError):
    pass


def conditional(error):
    return isinstance(error, ClientError) and error.response["Error"]["Code"] == "ConditionalCheckFailedException"


def issue(data, request_id, subject, table, s3, bucket, base_url, organization_id):
    if not isinstance(data, dict) or set(data) != set(FIELDS):
        raise ValueError("Provide recipient, course, organization, issue date and expiry date only.")
    if any(not isinstance(data[field], str) for field in FIELDS):
        raise ValueError("All certificate fields must be text.")
    data = {field: data[field].strip() for field in FIELDS}
    if not organization_id or data["organization"] != organization_name(organization_id):
        raise PermissionError("Certificates must use your assigned organization.")
    try:
        canonical_id = str(UUID(request_id))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("A valid issuance request ID is required.") from None
    identifier = "CERT-" + str(uuid5(NAMESPACE_URL, "ccd:" + subject + ":" + canonical_id))
    pdf, metadata = generate_certificate(data["recipient_name"], data["course_name"],
        data["organization"], data["issue_date"], data["expiry_date"], base_url,
        certificate_id=identifier)
    fingerprint = hashlib.sha256(json.dumps({**data, "verification_base_url": base_url},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    request_key = "ISSUE#" + hashlib.sha256((subject + ":" + canonical_id).encode()).hexdigest()
    reservation = {"certificate_id": request_key, "record_type": "ISSUANCE_REQUEST",
        "issued_certificate_id": identifier, "input_sha256": fingerprint,
        "pdf_sha256": metadata["pdf_sha256"]}
    try:
        table.put_item(Item=reservation, ConditionExpression="attribute_not_exists(certificate_id)")
    except Exception as error:
        # A read also recovers a write whose success response was lost.
        existing = table.get_item(Key={"certificate_id": request_key}, ConsistentRead=True).get("Item")
        if existing != reservation:
            if conditional(error) and existing:
                raise Conflict("This request was already used for different certificate details.") from None
            raise
    key = "certificates/" + identifier + ".pdf"
    item = {**metadata, "organization_id": organization_id, "s3_bucket": bucket, "s3_key": key, "issued_by": subject,
            "issuance_request_id": canonical_id}
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=pdf, ContentType="application/pdf",
                      ServerSideEncryption="AES256", IfNoneMatch="*")
    except ClientError as error:
        if error.response["Error"]["Code"] not in ("PreconditionFailed", "412"):
            raise
        body = s3.get_object(Bucket=bucket, Key=key)["Body"]
        try:
            if hashlib.sha256(body.read()).hexdigest() != metadata["pdf_sha256"]:
                raise Conflict("A different PDF exists. Nothing was overwritten.")
        finally:
            body.close()
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(certificate_id)")
    except Exception as error:
        existing = table.get_item(Key={"certificate_id": identifier}, ConsistentRead=True).get("Item")
        if existing != item:
            if conditional(error) and existing:
                raise Conflict("A different certificate record exists. Nothing was overwritten.") from None
            raise
    download = s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key,
        "ResponseContentDisposition": 'attachment; filename="' + identifier + '.pdf"'}, ExpiresIn=300)
    return {"certificate_id": identifier, "verification_url": metadata["verification_url"],
            "download_url": download, "download_expires_in": 300}


def lambda_handler(event, context):
    return allow_admin_origin(_handle(event, context), event)


def _handle(event, context):
    global _table, _s3, _sns
    denied = authorize(event)
    if denied is not None:
        return denied
    if (event.get("resource"), event.get("httpMethod")) in (
            ("/admin/certificates", "GET"), ("/admin/certificates/{id}/revoke", "POST")):
        try:
            if _table is None:
                _table = boto3.resource("dynamodb").Table(os.environ["CERTIFICATE_TABLE"])
            if _sns is None:
                _sns = boto3.client("sns", config=Config(connect_timeout=2, read_timeout=3,
                    retries={"total_max_attempts": 2, "mode": "standard"}))
            return manage(event, _table, _sns, os.environ.get("NOTIFICATION_TOPIC_ARN"),
                          os.environ["VERIFICATION_BASE_URL"])
        except Exception as error:
            logger.error("Management unavailable: type=%s", type(error).__name__)
            return response(503, {"error": "Certificate management is temporarily unavailable."})
    if event.get("resource") != "/admin/certificates" or event.get("httpMethod") != "POST":
        return response(404, {"error": "Route not found."})
    organization_id = assigned_organization(event)
    if not organization_id:
        return response(403, {"error": "Ask the account owner to assign your organization before issuing certificates."})
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    if headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        return response(415, {"error": "Send certificate details as JSON."})
    body = event.get("body")
    if event.get("isBase64Encoded") or not isinstance(body, str) or len(body.encode()) > 8192:
        return response(400, {"error": "Invalid certificate request."})
    try:
        data = json.loads(body)
        if _table is None:
            _table = boto3.resource("dynamodb").Table(os.environ["CERTIFICATE_TABLE"])
        if _s3 is None:
            _s3 = boto3.client("s3")
        result = issue(data, headers.get("idempotency-key"),
            event["requestContext"]["authorizer"]["claims"]["sub"], _table, _s3,
            os.environ["CERTIFICATE_BUCKET"], os.environ["VERIFICATION_BASE_URL"], organization_id)
        topic = os.environ.get("NOTIFICATION_TOPIC_ARN")
        if topic:
            try:
                if _sns is None:
                    _sns = boto3.client("sns", config=Config(connect_timeout=2, read_timeout=3,
                        retries={"total_max_attempts": 2, "mode": "standard"}))
                result["notification_status"] = publish_issuance(_table, _sns, topic, result)
            except Exception as error:
                logger.error("Notification pending: type=%s", type(error).__name__)
                result["notification_status"] = "pending"
        return response(201, result)
    except PermissionError as error:
        return response(403, {"error": str(error)})
    except Conflict as error:
        return response(409, {"error": str(error)})
    except ValueError as error:
        return response(400, {"error": str(error)})
    except Exception as error:
        logger.error("Issuance failed: type=%s request=%s", type(error).__name__,
                     getattr(context, "aws_request_id", "unknown"))
        return response(503, {"error": "Issuance could not be confirmed. Retry the same submission."})
