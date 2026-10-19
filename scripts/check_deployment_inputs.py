"""Fail before requesting AWS credentials if required private inputs are absent."""

import json
import os
import re
import sys


def main():
    mode = os.environ.get("DEPLOY_MODE")
    confirmation = os.environ.get("DEPLOY_CONFIRMATION", "")
    if mode not in {"plan", "apply"}:
        raise ValueError("Select plan or apply.")
    if mode == "apply" and confirmation != "DEPLOY":
        raise ValueError("To apply, enter DEPLOY in the confirmation field.")
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise ValueError("Deployment must run from main.")
    if os.environ.get("GITHUB_REPOSITORY") != "RAJULA-SAI-CHETAN-REDDY/Cloud_Certificate_System":
        raise ValueError("Unexpected GitHub repository.")
    try:
        organizations = json.loads(os.environ.get("TF_VAR_admin_organizations", ""))
    except json.JSONDecodeError as error:
        raise ValueError("Set the development ADMIN_ORGANIZATIONS_JSON secret to a JSON object.") from error
    if not isinstance(organizations, dict) or not organizations:
        raise ValueError("The administrator organization mapping must be nonempty.")
    for subject, organization in organizations.items():
        if not re.fullmatch(r"[0-9a-f-]{36}", subject) or not re.fullmatch(r"org-[1-9][0-9]{0,3}", str(organization)):
            raise ValueError("The administrator organization mapping has an invalid entry.")
    if not os.environ.get("TF_VAR_notification_email", "").strip():
        raise ValueError("Set the development NOTIFICATION_EMAIL secret.")
    print(f"Inputs are present for {mode}; private values were not displayed.")


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        sys.exit(str(error))
