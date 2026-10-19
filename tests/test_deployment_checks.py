import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.check_deployment_inputs import main as check_inputs
from scripts.check_deployment_plan import main as check_plan
from scripts.check_deployment_state import main as check_state


class DeploymentCheckTests(unittest.TestCase):
    def test_inputs_require_main_and_explicit_apply_confirmation(self):
        values = {
            "DEPLOY_MODE": "apply",
            "DEPLOY_CONFIRMATION": "",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_REPOSITORY": "RAJULA-SAI-CHETAN-REDDY/Cloud_Certificate_System",
            "TF_VAR_admin_organizations": '{"21a3bd6a-90a1-7004-0f68-c35e57e2233f":"org-1"}',
            "TF_VAR_notification_email": "admin@example.test",
        }
        with patch.dict(os.environ, values):
            with self.assertRaisesRegex(ValueError, "DEPLOY"):
                check_inputs()
            os.environ["DEPLOY_CONFIRMATION"] = "DEPLOY"
            check_inputs()
            os.environ["GITHUB_REF"] = "refs/heads/feature"
            with self.assertRaisesRegex(ValueError, "main"):
                check_inputs()

    def test_state_requires_existing_core_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "addresses.txt"
            path.write_text("aws_s3_bucket.certificates\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "incomplete"):
                check_state(path)

    def test_plan_rejects_storage_changes_and_non_api_deletions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"

            def check(address, kind, actions):
                path.write_text(json.dumps({"resource_changes": [{
                    "address": address, "type": kind, "change": {"actions": actions}
                }]}), encoding="utf-8")
                check_plan(path)

            with self.assertRaisesRegex(ValueError, "Protected storage"):
                check("aws_s3_bucket.certificates", "aws_s3_bucket", ["update"])
            with self.assertRaisesRegex(ValueError, "Destructive"):
                check("aws_lambda_function.verification", "aws_lambda_function", ["delete", "create"])
            check("aws_api_gateway_deployment.verification", "aws_api_gateway_deployment", ["create", "delete"])
            check("aws_lambda_function.verification", "aws_lambda_function", ["update"])


if __name__ == "__main__":
    unittest.main()
