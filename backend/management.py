"""Bounded administrator listing and irreversible, retry-safe revocation."""
import logging
from datetime import datetime, timezone

try:
    from .admin_auth import response
    from .verification import ID_PATTERN, public_result
    from .notifications import publish_event
    from .organizations import assigned_organization, can_manage, record_organization
except ImportError:
    from admin_auth import response
    from verification import ID_PATTERN, public_result
    from notifications import publish_event
    from organizations import assigned_organization, can_manage, record_organization

logger = logging.getLogger(__name__)


def list_certificates(table, query, organization):
    cursor = query.get("cursor")
    if cursor is not None and (not isinstance(cursor, str) or not 1 <= len(cursor) <= 200):
        raise ValueError("Invalid page cursor.")
    args = dict(Limit=25, ConsistentRead=True,
                FilterExpression="begins_with(certificate_id, :prefix) AND attribute_not_exists(retired_at)",
                ExpressionAttributeValues={":prefix": "CERT-"})
    if cursor:
        args["ExclusiveStartKey"] = {"certificate_id": cursor}
    page = table.scan(**args)
    records = [{**public_result(item, item["certificate_id"]),
                "organization_id": record_organization(item), "can_manage": can_manage(item, organization)}
               for item in page.get("Items", [])
               if ID_PATTERN.fullmatch(item.get("certificate_id", "")) and not item.get("retired_at")]
    # Scan limits evaluated records, so an empty page can still have a next page.
    return {"certificates": records,
            "next_cursor": page.get("LastEvaluatedKey", {}).get("certificate_id")}


def revoke(table, identifier, subject, organization):
    if not isinstance(identifier, str) or not ID_PATTERN.fullmatch(identifier):
        raise ValueError("Enter a valid certificate ID.")
    key = {"certificate_id": identifier}
    record = table.get_item(Key=key, ConsistentRead=True).get("Item")
    if record is None:
        return None
    if not can_manage(record, organization):
        raise PermissionError("You can manage only your organization's certificates.")
    public_result(record, identifier)  # Reject corrupt records before changing anything.
    if record["status"] != "REVOKED":
        ownership = "organization_id = :organization"
        values = {":organization": organization}
        if "organization_id" not in record:
            # Only the exact known legacy ID checked by can_manage is eligible.
            ownership = "attribute_not_exists(organization_id)"
            values = {}
        try:
            record = table.update_item(Key=key,
                UpdateExpression="SET #s = :revoked, revoked_at = :at, revoked_by = :by",
                ConditionExpression="attribute_exists(certificate_id) AND #s = :active AND attribute_not_exists(retired_at) AND " + ownership,
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":revoked": "REVOKED", ":active": "ACTIVE",
                    ":at": datetime.now(timezone.utc).isoformat(), ":by": subject, **values},
                ReturnValues="ALL_NEW")["Attributes"]
        except Exception:
            # Includes concurrent revocation and a lost successful write response.
            current = table.get_item(Key=key, ConsistentRead=True).get("Item")
            if not current or current.get("status") != "REVOKED" or not can_manage(current, organization):
                raise
            record = current
    return record


def handle(event, table, sns, topic, base_url):
    try:
        organization = assigned_organization(event)
        if event.get("httpMethod") == "GET" and event.get("resource") == "/admin/certificates":
            return response(200, list_certificates(table, event.get("queryStringParameters") or {}, organization))
        identifier = (event.get("pathParameters") or {}).get("id")
        record = revoke(table, identifier, event["requestContext"]["authorizer"]["claims"]["sub"], organization)
        if record is None:
            return response(404, {"error": "Certificate not found."})
        notification = "pending"
        try:
            if topic:
                notification = publish_event(table, sns, topic, {
                    "certificate_id": identifier,
                    "verification_url": base_url + "?id=" + identifier}, "REVOKED")
        except Exception as error:
            logger.error("Revocation notification pending: type=%s", type(error).__name__)
        return response(200, {"certificate_id": identifier, "status": "REVOKED",
                              "notification_status": notification})
    except PermissionError as error:
        return response(403, {"error": str(error)})
    except ValueError as error:
        return response(400, {"error": str(error)})
    except Exception as error:
        logger.error("Management failed: type=%s", type(error).__name__)
        return response(503, {"error": "Operation could not be confirmed. Retry the same certificate."})
