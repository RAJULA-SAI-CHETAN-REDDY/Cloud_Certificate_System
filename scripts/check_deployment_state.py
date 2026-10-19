"""Reject a missing or incomplete remote state before any cloud plan."""

import sys
from pathlib import Path


REQUIRED = {
    "aws_s3_bucket.certificates",
    "aws_dynamodb_table.certificates",
    "aws_cloudfront_distribution.frontend",
    "aws_api_gateway_rest_api.verification",
}


def main(path):
    addresses = set(Path(path).read_text(encoding="utf-8").splitlines())
    missing = REQUIRED - addresses
    if missing:
        raise ValueError("Existing Terraform state is incomplete: " + ", ".join(sorted(missing)))
    print(f"Existing development state confirmed ({len(addresses)} resource addresses).")


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except (IndexError, OSError, ValueError) as error:
        sys.exit(str(error))
