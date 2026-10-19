"""Authorization for routes protected by the API Gateway Cognito authorizer."""

import json
import math
import os
import time
from datetime import datetime, timezone
try:
    from .organizations import assigned_organization, organization_name
except ImportError:
    from organizations import assigned_organization, organization_name


def response(code, body):
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "http://localhost:8000",
            "Vary": "Origin",
        },
        "body": json.dumps(body),
    }


def allow_admin_origin(result, event):
    """Return CORS only for the two registered administrator site origins."""
    request_headers = {str(key).lower(): value for key, value in (event.get("headers") or {}).items()}
    origin = request_headers.get("origin")
    allowed = {"http://localhost:8000", os.environ.get("ADMIN_WEBSITE_ORIGIN")}
    headers = result.setdefault("headers", {})
    if origin in allowed:
        headers["Access-Control-Allow-Origin"] = origin
    else:
        headers.pop("Access-Control-Allow-Origin", None)
    return result


def groups(value):
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        return []
    # REST API claims can serialize the Cognito array as [admins,other].
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            value = value[1:-1]
    return [group.strip() for group in value.split(",")]


def expiry_timestamp(value):
    if isinstance(value, bool):
        raise ValueError("Invalid expiry")
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        if not isinstance(value, str):
            raise ValueError("Invalid expiry")
        # REST Cognito authorizers can format exp rather than retain JWT seconds.
        timestamp = datetime.strptime(value, "%a %b %d %H:%M:%S UTC %Y").replace(
            tzinfo=timezone.utc
        ).timestamp()
    if not math.isfinite(timestamp):
        raise ValueError("Invalid expiry")
    return timestamp


def authorize(event):
    context = event.get("requestContext") or {}
    authorizer = context.get("authorizer") or {}
    claims = authorizer.get("claims") or {}
    if not isinstance(claims, dict):
        return response(401, {"error": "Sign in to continue."})
    issuer = os.environ.get("ADMIN_ISSUER")
    client_id = os.environ.get("ADMIN_CLIENT_ID")
    try:
        valid = (
            bool(issuer) and bool(client_id)
            and claims.get("iss") == issuer
            and claims.get("aud") == client_id
            and claims.get("token_use") == "id"
            and isinstance(claims.get("sub"), str) and bool(claims["sub"])
            and expiry_timestamp(claims.get("exp")) > time.time()
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        return response(401, {"error": "Sign in to continue."})
    if "admins" not in groups(claims.get("cognito:groups")):
        return response(403, {"error": "Administrator access required."})
    return None


def session(event):
    denied = authorize(event)
    if denied is not None:
        return denied
    if event.get("resource") != "/admin/session" or event.get("httpMethod") != "GET":
        return response(404, {"error": "Route not found."})
    organization = assigned_organization(event)
    return response(200, {"authorized": True, "role": "Administrator",
        "organization_id": organization,
        "organization": organization_name(organization) if organization else None})
