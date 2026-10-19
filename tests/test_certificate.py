import hashlib
import unittest

from backend.generate_certificate import generate_certificate


class CertificateTests(unittest.TestCase):
    def generate(self, **changes):
        data = dict(recipient="Rahul Sharma", course="Cloud Computing",
                    organization="ABC Institute", issue_date="2026-10-03",
                    expiry_date="2027-10-03",
                    verification_base_url="http://localhost:8000/verify.html")
        data.update(changes)
        return generate_certificate(**data)

    def test_final_pdf_integrity_and_unique_id(self):
        pdf, metadata = self.generate()
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertEqual(hashlib.sha256(pdf).hexdigest(), metadata["pdf_sha256"])
        self.assertNotEqual(hashlib.sha256(pdf + b"changed").hexdigest(), metadata["pdf_sha256"])
        self.assertNotEqual(metadata["certificate_id"], self.generate()[1]["certificate_id"])
        self.assertIn(metadata["certificate_id"], metadata["verification_url"])

    def test_invalid_inputs(self):
        for change in ({"recipient": " "}, {"course": "x" * 121},
                       {"expiry_date": "2025-01-01"}, {"issue_date": "bad"},
                       {"verification_base_url": "javascript:alert(1)"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.generate(**change)


if __name__ == "__main__":
    unittest.main()
