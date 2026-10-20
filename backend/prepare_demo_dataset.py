"""Prepare 51 synthetic certificates; --apply uploads them without notifications.

This is a development-only maintenance import using the existing developer IAM
identity. It never calls the issuance API or SNS, and never overwrites an
existing certificate or PDF with different content.
"""

import argparse
import csv
import io
import json
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import boto3

try:
    from .generate_certificate import generate_certificate
    from .upload_certificate import load_certificate, upload
except ImportError:
    from generate_certificate import generate_certificate
    from upload_certificate import load_certificate, upload


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "demo_students.csv"
OUTPUT = ROOT / "output" / "demo-students"
BUCKET = "ccd-certificates-707256068320-ap-south-1"
TABLE = "ccd-certificates"
DEVELOPER_ARN = "arn:aws:iam::707256068320:user/ccd-developer"
VERIFICATION_URL = "https://d6uwrv2kb0dl8.cloudfront.net/verify.html"
COLUMNS = ("recipient_name", "course_name", "organization_id", "organization", "issue_date", "expiry_date")


def read_dataset(path=DATASET):
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError("Demo dataset columns changed; review the CSV before importing.")
        rows = list(reader)
    if len(rows) != 51 or len({row["recipient_name"] for row in rows}) != 51:
        raise ValueError("Expected 51 distinct synthetic students.")
    counts = Counter(row["organization_id"] for row in rows)
    if counts != {"org-1": 17, "org-2": 17, "org-3": 17}:
        raise ValueError("Expected 17 students in each of the three organizations.")
    for row in rows:
        if not row["recipient_name"].startswith("Demo Student "):
            raise ValueError("Only clearly labeled demo students may be imported.")
        if row["organization"] != "Organization " + row["organization_id"][-1]:
            raise ValueError("Organization ID and name do not match.")
    return rows


def prepare(rows, directory=OUTPUT):
    directory.mkdir(parents=True, exist_ok=True)
    prepared = []
    for row in rows:
        identifier = "CERT-" + str(uuid5(NAMESPACE_URL,
            "ccd:demo-students:v1:" + row["organization_id"] + ":" + row["recipient_name"]))
        pdf, record = generate_certificate(row["recipient_name"], row["course_name"],
            row["organization"], row["issue_date"], row["expiry_date"],
            VERIFICATION_URL, certificate_id=identifier)
        record["organization_id"] = row["organization_id"]
        record["dataset"] = "synthetic-demo-students-v1"
        stem = directory / identifier
        metadata_path = stem.with_suffix(".json")
        for path, content in ((stem.with_suffix(".pdf"), pdf),
                              (metadata_path, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode())):
            if path.exists() and path.read_bytes() != content:
                raise ValueError(f"Prepared file differs: {path.name}; nothing was overwritten.")
            path.write_bytes(content)
        checked_pdf, checked_record = load_certificate(metadata_path)
        if checked_pdf != pdf or checked_record != record:
            raise ValueError(f"Prepared certificate failed validation: {identifier}")
        prepared.append((pdf, record))
    return prepared


def apply(prepared, session):
    caller = session.client("sts").get_caller_identity()["Arn"]
    if caller != DEVELOPER_ARN:
        raise ValueError("Use the existing ccd-developer profile for this maintenance import.")
    table = session.resource("dynamodb").Table(TABLE)
    # Check every ID before the first write, so a conflict cannot cause a
    # partial import. upload() also uses conditional S3/DynamoDB writes.
    existing = 0
    for _, record in prepared:
        found = table.get_item(Key={"certificate_id": record["certificate_id"]}, ConsistentRead=True).get("Item")
        if found is not None:
            expected = {**record, "s3_bucket": BUCKET,
                        "s3_key": f"certificates/{record['certificate_id']}.pdf"}
            if found != expected:
                raise ValueError("A different record already uses a demo ID; nothing was uploaded.")
            existing += 1
    for pdf, record in prepared:
        with redirect_stdout(io.StringIO()):
            upload(pdf, record, BUCKET, TABLE, session)
    print(f"Confirmed {len(prepared)} synthetic certificates: {len(prepared) - existing} new, {existing} already identical.")
    print("No notification events were sent by this import.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Upload the reviewed demo dataset to the existing development account")
    args = parser.parse_args()
    try:
        prepared = prepare(read_dataset())
        if args.apply:
            apply(prepared, boto3.Session(profile_name="ccd", region_name="ap-south-1"))
        else:
            print(f"Prepared {len(prepared)} synthetic PDFs and metadata files in {OUTPUT}.")
            print("No AWS call or email was made. Review the dataset before --apply.")
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f"Demo dataset preparation failed: {error}\n")


if __name__ == "__main__":
    main()
