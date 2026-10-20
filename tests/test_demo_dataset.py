import hashlib
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend import prepare_demo_dataset


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
        with patch.object(prepare_demo_dataset, "upload") as upload:
            with self.assertRaisesRegex(ValueError, "different record"):
                prepare_demo_dataset.apply(prepared, session)
            upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
