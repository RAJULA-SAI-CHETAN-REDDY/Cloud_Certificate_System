"""Hide four known development test records from the admin list, preserving history.

Preview is read-only. --apply marks only records with the exact expected IDs and
names as retired. Private PDFs and hashes remain intact. No SNS event is sent.
"""

import argparse
from datetime import datetime, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError

try:
    from .prepare_demo_dataset import DEVELOPER_ARN, TABLE
except ImportError:
    from prepare_demo_dataset import DEVELOPER_ARN, TABLE


SAMPLES = {
    "CERT-fe669248-fea3-564f-9e01-f9c6211ec503": "Student 1",
    "CERT-9a2985ed-0610-5582-9ee2-ba8208bc8064": "Student 2",
    "CERT-556863f6-12f2-5368-ad00-1b41f27df35d": "Student 3",
    "CERT-61a7b54a-987f-51a2-9483-ef61431f1f8e": "HTTPS QR Demo Student",
}


def run(session, apply_changes=False):
    caller = session.client("sts").get_caller_identity()["Arn"]
    if caller != DEVELOPER_ARN:
        raise ValueError("Use the ccd-developer profile for sample retirement.")
    table = session.resource("dynamodb").Table(TABLE)
    found = []
    for identifier, name in SAMPLES.items():
        item = table.get_item(Key={"certificate_id": identifier}, ConsistentRead=True).get("Item")
        if not item or item.get("recipient_name") != name or not item.get("pdf_sha256"):
            raise ValueError(f"Expected test record missing or changed: {identifier}; no changes made.")
        found.append(item)
    pending = [item for item in found if not item.get("retired_at")]
    for item in found:
        print(f"{item['recipient_name']}: {item['certificate_id']} - " +
              ("already retired" if item.get("retired_at") else "visible; ready to retire"))
    if not apply_changes:
        print("Read-only preview. No AWS record or email changed.")
        return
    for item in pending:
        identifier = item["certificate_id"]
        now = datetime.now(timezone.utc).isoformat()
        table.update_item(
            Key={"certificate_id": identifier},
            UpdateExpression="SET retired_at = :at, #s = :revoked, revoked_at = if_not_exists(revoked_at, :at), revoked_by = if_not_exists(revoked_by, :by)",
            ConditionExpression="attribute_exists(certificate_id) AND recipient_name = :name AND pdf_sha256 = :hash AND attribute_not_exists(retired_at)",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":at": now, ":revoked": "REVOKED", ":by": "development-demo-cleanup",
                                       ":name": item["recipient_name"], ":hash": item["pdf_sha256"]},
        )
    print(f"Retired {len(pending)} exact test records. PDFs and record history remain; no email sent.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Retire the four reviewed test records")
    args = parser.parse_args()
    try:
        run(boto3.Session(profile_name="ccd", region_name="ap-south-1"), args.apply)
    except (ValueError, BotoCoreError, ClientError) as error:
        parser.exit(1, f"Sample retirement stopped: {error}\n")


if __name__ == "__main__":
    main()
