"""Reject destructive plans before GitHub can apply them."""

import json
import sys
from pathlib import Path


PROTECTED = {
    "aws_s3_bucket.certificates",
    "aws_dynamodb_table.certificates",
    "aws_s3_bucket.frontend",
}


def main(path):
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    changes = []
    for resource in plan.get("resource_changes", []):
        actions = resource["change"]["actions"]
        if actions == ["no-op"]:
            continue
        address = resource["address"]
        if address in PROTECTED:
            raise ValueError(f"Protected storage resource would change: {address}")
        if "delete" in actions and resource["type"] != "aws_api_gateway_deployment":
            raise ValueError(f"Destructive change requires local review: {address}")
        changes.append(f"{address}: {', '.join(actions)}")
    print(f"Allowed resource changes: {len(changes)}")
    for change in changes:
        print(change)


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except (IndexError, OSError, KeyError, ValueError) as error:
        sys.exit(str(error))
