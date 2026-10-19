"""Generate a local certificate PDF and its integrity reference. No AWS needed."""

import argparse
import hashlib
import io
import json
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4
import re

import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


def generate_certificate(recipient, course, organization, issue_date, expiry_date,
                         verification_base_url, certificate_id=None):
    """Return final PDF bytes and metadata; keep storage separate for future Lambda use."""
    for label, value in (("Recipient", recipient), ("Course", course),
                         ("Organization", organization)):
        if not value.strip() or len(value) > 120:
            raise ValueError(f"{label} must contain 1 to 120 characters.")
        if any(ord(character) < 32 or ord(character) > 126 for character in value):
            raise ValueError(f"{label} currently supports printable English characters only.")
    issued = date.fromisoformat(issue_date)
    expires = date.fromisoformat(expiry_date)
    if expires < issued:
        raise ValueError("Expiry date must not precede issue date.")
    url = urlsplit(verification_base_url)
    if url.scheme not in ("http", "https") or not url.netloc or url.fragment:
        raise ValueError("Verification URL must be an HTTP(S) URL without a fragment.")
    deterministic = certificate_id is not None
    if certificate_id is None:
        certificate_id = "CERT-" + str(uuid4())
    if not re.fullmatch(r"CERT-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", certificate_id):
        raise ValueError("Invalid certificate ID.")
    query = [(key, value) for key, value in parse_qsl(url.query)
             if key != "id"] + [("id", certificate_id)]
    verification_url = urlunsplit(url._replace(query=urlencode(query)))
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=10, border=4)
    qr.add_data(verification_url)
    qr.make(fit=True)
    qr_image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buffer = io.BytesIO()
    width, height = landscape(A4)
    pdf = canvas.Canvas(buffer, pagesize=(width, height), invariant=deterministic)
    pdf.setTitle(f"Certificate of completion - {recipient.strip()}")
    pdf.setAuthor(organization.strip())
    navy = colors.HexColor("#17324D")
    pdf.setFillColor(colors.HexColor("#FAFAF6"))
    pdf.rect(0, 0, width, height, fill=1, stroke=0)
    pdf.setStrokeColor(navy)
    pdf.setLineWidth(2)
    pdf.rect(28, 28, width - 56, height - 56)

    def centered(text, y, size, font="Helvetica", max_width=700):
        while stringWidth(text, font, size) > max_width and size > 8:
            size -= 0.5
        pdf.setFillColor(navy)
        pdf.setFont(font, size)
        pdf.drawCentredString(width / 2, y, text)

    centered(organization.strip(), 510, 20, "Helvetica-Bold")
    centered("CERTIFICATE OF COMPLETION", 450, 30, "Helvetica-Bold")
    centered("This certificate is awarded to", 395, 14)
    centered(recipient.strip(), 347, 32, "Helvetica-Bold")
    centered("for successfully completing", 310, 14)
    centered(course.strip(), 270, 23, "Helvetica-Bold")
    pdf.setFillColor(navy)
    pdf.setFont("Helvetica", 11)
    pdf.drawString(66, 191, f"Issued: {issued.isoformat()}")
    pdf.drawString(66, 170, f"Expires: {expires.isoformat()}")
    pdf.setFont("Helvetica", 9)
    pdf.drawString(66, 132, "Certificate ID")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(66, 114, certificate_id)
    pdf.drawImage(ImageReader(qr_image), width - 209, 91, width=130, height=130)
    pdf.setFont("Helvetica", 9)
    pdf.drawCentredString(width - 144, 78, "Scan to check certificate status")
    centered("SAMPLE - development certificate", 49, 9)
    pdf.showPage()
    pdf.save()
    pdf_bytes = buffer.getvalue()
    metadata = {
        "certificate_id": certificate_id, "recipient_name": recipient.strip(),
        "course_name": course.strip(), "organization": organization.strip(),
        "issue_date": issued.isoformat(), "expiry_date": expires.isoformat(),
        "status": "ACTIVE", "pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "verification_url": verification_url,
    }
    return pdf_bytes, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipient", default="Rahul Sharma")
    parser.add_argument("--course", default="Cloud Computing")
    parser.add_argument("--organization", default="Organization 1")
    parser.add_argument("--issue-date", default="2026-10-03")
    parser.add_argument("--expiry-date", default="2027-10-03")
    parser.add_argument("--verification-url", default="http://localhost:8000/verify.html")
    parser.add_argument("--output-dir", type=Path, default=Path("output/pdf"))
    args = parser.parse_args()
    try:
        pdf_bytes, metadata = generate_certificate(
            args.recipient, args.course, args.organization, args.issue_date,
            args.expiry_date, args.verification_url)
    except ValueError as error:
        parser.error(str(error))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = args.output_dir / metadata["certificate_id"]
    stem.with_suffix(".pdf").write_bytes(pdf_bytes)
    stem.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"PDF: {stem.with_suffix('.pdf').resolve()}")
    print(f"Metadata: {stem.with_suffix('.json').resolve()}")
    print(f"SHA-256: {metadata['pdf_sha256']}")
    print("To open the local QR link, run: .venv\\Scripts\\python.exe backend/local_server.py")


if __name__ == "__main__":
    main()
