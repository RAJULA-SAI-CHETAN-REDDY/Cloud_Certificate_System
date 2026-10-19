"""Trusted organization assignments. Browser fields never grant access."""
import json
import os
import re

ORG_PATTERN = re.compile(r"org-([1-9][0-9]{0,3})")
# Existing development samples predate organization IDs. Match exact IDs, never
# user-editable display names. Retirement preserves their original PDFs/hashes.
LEGACY_ORGANIZATIONS = {
    "CERT-ffbc1c10-c6dd-4d03-b52a-ae0605a1240c": "org-1",
    "CERT-8ea4905d-cf06-55e1-9caf-c7d406460a1d": "org-2",
    "CERT-4687d791-33f5-5d9e-83e2-006e0b9293e8": "org-3",
}


def organization_name(identifier):
    match = ORG_PATTERN.fullmatch(identifier) if isinstance(identifier, str) else None
    if not match:
        raise ValueError("Invalid organization assignment.")
    return "Organization " + match.group(1)


def assigned_organization(event):
    """Use the gateway-verified subject and deployment-controlled assignments."""
    subject = event["requestContext"]["authorizer"]["claims"]["sub"]
    try:
        assignments = json.loads(os.environ.get("ADMIN_ORGANIZATIONS", "{}"))
        identifier = assignments.get(subject)
        if identifier is None:
            return None
        organization_name(identifier)
        return identifier
    except (ValueError, TypeError, AttributeError):
        # A broken configuration must never open management to all organizations.
        return None


def record_organization(record):
    identifier = record.get("organization_id")
    if identifier is None:
        identifier = LEGACY_ORGANIZATIONS.get(record.get("certificate_id"))
    try:
        organization_name(identifier)
        return identifier
    except ValueError:
        return None


def can_manage(record, organization):
    return bool(organization) and record_organization(record) == organization and not record.get("retired_at")
