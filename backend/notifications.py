"""Retryable issuance notifications; SNS acceptance is not email delivery proof."""

import time
from uuid import uuid4

from botocore.exceptions import ClientError


def publish_issuance(table, sns, topic_arn, certificate):
    return publish_event(table, sns, topic_arn, certificate, "ISSUED")


def publish_event(table, sns, topic_arn, certificate, event):
    if event not in ("ISSUED", "REVOKED"):
        raise ValueError("Unsupported certificate event")
    identifier = certificate["certificate_id"]
    key = {"certificate_id": "NOTIFY#" + event + "#" + identifier}
    existing = table.get_item(Key=key, ConsistentRead=True).get("Item", {})
    if existing.get("notification_status") == "PUBLISHED":
        return "published"
    now, owner = int(time.time()), str(uuid4())
    try:
        table.update_item(Key=key,
            UpdateExpression="SET #s = :working, lease_until = :until, lease_owner = :owner, record_type = :type",
            ConditionExpression="(attribute_not_exists(#s) OR #s <> :done) AND (attribute_not_exists(lease_until) OR lease_until < :now)",
            ExpressionAttributeNames={"#s": "notification_status"},
            ExpressionAttributeValues={":working": "PUBLISHING", ":done": "PUBLISHED",
                ":until": now + 60, ":now": now, ":owner": owner, ":type": "NOTIFICATION_EVENT"})
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        current = table.get_item(Key=key, ConsistentRead=True).get("Item", {})
        return "published" if current.get("notification_status") == "PUBLISHED" else "pending"

    # A lost publish acknowledgement may have delivered: wait for the lease before
    # retrying. Standard SNS cannot guarantee exactly-once email delivery.
    result = sns.publish(TopicArn=topic_arn, Subject="CCD development certificate " + event.lower(),
        Message="\n".join(["A development certificate was " + event.lower() + ".",
            "Certificate ID: " + identifier, "Verification: " + certificate["verification_url"],
            "Local verification links require the development computer's server.",
            "Event ID: " + event + "#" + identifier]))
    message_id = result["MessageId"]
    try:
        table.update_item(Key=key,
            UpdateExpression="SET #s = :done, sns_message_id = :message REMOVE lease_until, lease_owner",
            ConditionExpression="lease_owner = :owner AND #s = :working",
            ExpressionAttributeNames={"#s": "notification_status"},
            ExpressionAttributeValues={":done": "PUBLISHED", ":working": "PUBLISHING",
                ":owner": owner, ":message": message_id})
    except Exception:
        current = table.get_item(Key=key, ConsistentRead=True).get("Item", {})
        if current.get("notification_status") != "PUBLISHED":
            raise
    return "published"
