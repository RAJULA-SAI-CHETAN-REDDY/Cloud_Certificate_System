import copy
import unittest
from unittest.mock import patch

from botocore.exceptions import ClientError
from backend.notifications import publish_issuance, publish_event


CERTIFICATE = {"certificate_id": "CERT-test", "verification_url": "http://localhost:8000/verify.html?id=CERT-test",
               "download_url": "https://private.example/secret"}


class Table:
    def __init__(self):
        self.item = {}
        self.lose_completion = False
        self.fail_completion = False

    def get_item(self, **kwargs):
        assert kwargs["ConsistentRead"]
        return {"Item": copy.deepcopy(self.item)}

    def update_item(self, **kwargs):
        assert kwargs["Key"]["certificate_id"].startswith(("NOTIFY#ISSUED#", "NOTIFY#REVOKED#"))
        values = kwargs["ExpressionAttributeValues"]
        if ":now" in values:
            if (self.item.get("notification_status") == "PUBLISHED" or
                    self.item.get("lease_until", -1) >= values[":now"]):
                raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")
            self.item.update(notification_status="PUBLISHING", lease_until=values[":until"],
                             lease_owner=values[":owner"])
        else:
            assert values[":owner"] == self.item["lease_owner"]
            if self.fail_completion:
                raise RuntimeError("private database error")
            self.item.update(notification_status="PUBLISHED", sns_message_id=values[":message"])
            self.item.pop("lease_until")
            self.item.pop("lease_owner")
            if self.lose_completion:
                raise RuntimeError("lost completion response")


class SNS:
    def __init__(self):
        self.messages = []
        self.fail = False
        self.on_publish = None

    def publish(self, **kwargs):
        self.messages.append(kwargs)
        if self.on_publish:
            self.on_publish()
        if self.fail:
            raise RuntimeError("private SNS failure")
        return {"MessageId": "test-message-id"}


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.table, self.sns = Table(), SNS()

    def publish(self):
        return publish_issuance(self.table, self.sns, "topic", CERTIFICATE)

    def test_success_replay_and_private_link_exclusion(self):
        self.assertEqual(self.publish(), "published")
        self.assertEqual(self.publish(), "published")
        self.assertEqual(len(self.sns.messages), 1)
        self.assertIn("Event ID: ISSUED#CERT-test", self.sns.messages[0]["Message"])
        self.assertNotIn("secret", self.sns.messages[0]["Message"])

    def test_overlapping_retry_does_not_publish(self):
        self.sns.on_publish = lambda: self.assertEqual(self.publish(), "pending")
        self.assertEqual(self.publish(), "published")
        self.assertEqual(len(self.sns.messages), 1)

    def test_failed_publish_waits_for_lease_then_retries(self):
        self.sns.fail = True
        with patch("backend.notifications.time.time", return_value=1000):
            with self.assertRaises(RuntimeError):
                self.publish()
            self.assertEqual(self.publish(), "pending")
        self.sns.fail = False
        with patch("backend.notifications.time.time", return_value=1061):
            self.assertEqual(self.publish(), "published")
        self.assertEqual(len(self.sns.messages), 2)

    def test_lost_completion_readback_avoids_republishing(self):
        self.table.lose_completion = True
        self.assertEqual(self.publish(), "published")
        self.assertEqual(self.publish(), "published")
        self.assertEqual(len(self.sns.messages), 1)

    def test_failed_completion_keeps_lease(self):
        self.table.fail_completion = True
        with self.assertRaises(RuntimeError):
            self.publish()
        self.assertEqual(self.publish(), "pending")
        self.assertEqual(len(self.sns.messages), 1)


class RevocationNotificationTests(NotificationTests):
    def publish(self):
        return publish_event(self.table, self.sns, "topic", CERTIFICATE, "REVOKED")

    def test_success_replay_and_private_link_exclusion(self):
        self.assertEqual(self.publish(), "published")
        self.assertEqual(self.publish(), "published")
        self.assertEqual(len(self.sns.messages), 1)
        self.assertIn("Event ID: REVOKED#CERT-test", self.sns.messages[0]["Message"])
        self.assertNotIn("secret", self.sns.messages[0]["Message"])
