import hashlib
import tempfile
import unittest
from collections import Counter
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend import prepare_demo_dataset
from backend import retire_initial_samples
from backend.verification import public_result


class DemoDatasetTests(unittest.TestCase):
    def test_prepared_samples_are_unique_balanced_and_repeatable(self):
        rows = prepare_demo_dataset.read_dataset()
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            first = prepare_demo_dataset.prepare(rows, directory)
            second = prepare_demo_dataset.prepare(rows, directory)
            self.assertEqual(first, second)
            self.assertEqual(len(first), 51)
            self.assertEqual(len({record["certificate_id"] for _, record in first}), 51)
            self.assertEqual(Counter(record["organization_id"] for _, record in first),
                             {"org-1": 17, "org-2": 17, "org-3": 17})
            self.assertEqual(Counter(public_result(record, record["certificate_id"],
                                        today=date(2026, 10, 20))["status"]
                                     for _, record in first),
                             {"ACTIVE": 42, "EXPIRED": 6, "REVOKED": 3})
            self.assertTrue(all(record["recipient_name"].startswith("Demo Student ")
                                and record["verification_url"].startswith(prepare_demo_dataset.VERIFICATION_URL)
                                and pdf.startswith(b"%PDF-")
                                and record["pdf_sha256"] == hashlib.sha256(pdf).hexdigest()
                                for pdf, record in first))

    def test_conflicting_existing_record_stops_before_upload(self):
        session = MagicMock()
        session.client.return_value.get_caller_identity.return_value = {"Arn": prepare_demo_dataset.DEVELOPER_ARN}
        table = session.resource.return_value.Table.return_value
        table.get_item.side_effect = [{}, {"Item": {"certificate_id": "different"}}]
        prepared = [(b"%PDF-test", {"certificate_id": "CERT-first"}),
                    (b"%PDF-test", {"certificate_id": "CERT-second"})]
        with patch.object(prepare_demo_dataset, "upload_one") as upload:
            with self.assertRaisesRegex(ValueError, "different record"):
                prepare_demo_dataset.apply(prepared, session)
            upload.assert_not_called()

    def test_upload_uses_conditional_private_storage_without_notifications(self):
        session, table = MagicMock(), MagicMock()
        record = {"certificate_id": "CERT-example", "pdf_sha256": "abc"}
        prepare_demo_dataset.upload_one(b"%PDF-test", record, session, table)
        session.client.assert_called_once_with("s3")
        self.assertEqual(session.client.return_value.put_object.call_args.kwargs["IfNoneMatch"], "*")
        self.assertEqual(session.client.return_value.put_object.call_args.kwargs["ServerSideEncryption"], "AES256")
        self.assertEqual(table.put_item.call_args.kwargs["ConditionExpression"],
                         "attribute_not_exists(certificate_id)")

    def test_initial_sample_retirement_requires_exact_names_and_preview_does_not_write(self):
        session = MagicMock()
        session.client.return_value.get_caller_identity.return_value = {"Arn": prepare_demo_dataset.DEVELOPER_ARN}
        table = session.resource.return_value.Table.return_value
        records = [{"certificate_id": identifier, "recipient_name": name,
                    "pdf_sha256": "a" * 64, "status": "ACTIVE"}
                   for identifier, name in retire_initial_samples.SAMPLES.items()]
        table.get_item.side_effect = [{"Item": row} for row in records]
        retire_initial_samples.run(session)
        table.update_item.assert_not_called()
        table.get_item.side_effect = [{"Item": row} for row in records]
        retire_initial_samples.run(session, True)
        self.assertEqual(table.update_item.call_count, 4)
        table.reset_mock()
        records[1]["recipient_name"] = "Someone else"
        table.get_item.side_effect = [{"Item": row} for row in records]
        with self.assertRaisesRegex(ValueError, "missing or changed"):
            retire_initial_samples.run(session, True)
        table.update_item.assert_not_called()


if __name__ == "__main__":
    unittest.main()
