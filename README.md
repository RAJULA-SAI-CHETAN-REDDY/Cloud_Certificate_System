# Cloud Certificate System

A development certificate registry with administrator issuance and revocation,
public ID and QR verification, optional exact PDF comparison, and email events.
The source requirements are the three Word documents in [`docs/`](docs/).

The current development site is hosted through CloudFront. The public lookup,
administrator sign-in and listing, issuance, revocation, PDF comparison, phone
QR lookup, and issuance/revocation email delivery have been tested. The
administrator list now uses a compact certificate table. The uploaded
PDF hash detects changed bytes when compared with the stored reference; it is
not proof of issuer identity. Older demonstration PDFs may still contain
localhost QR links. A newly issued demo PDF was tested with the HTTPS QR link.

## Project layout

- `backend/`: certificate generation, verification, administrator APIs, and
  Lambda packaging scripts.
- `frontend/`: public and administrator pages, source scripts, and the built
  browser files used by Terraform.
- `infrastructure/`: Terraform for the existing AWS development environment.
- `tests/`: Python and browser tests.
- `docs/`: original source requirements and updated flowcharts.

## Local setup on Windows

Open PowerShell in the project folder. Python 3.12, Node.js, AWS CLI, and
Terraform are needed for the relevant tasks.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm.cmd --prefix frontend ci --ignore-scripts
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe backend/local_server.py
```

Open http://localhost:8000/. Stop the local server with Ctrl+C. The
administrator login callback is registered for localhost port 8000; opening
files directly or using another local host name will not sign in.

## Checks and build

From the project folder:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm.cmd --prefix frontend test
.\.venv\Scripts\python.exe backend/package_verification.py
.\.venv\Scripts\python.exe backend/package_issuance.py
terraform -chdir=infrastructure validate
```

For a fresh local browser-test setup, run `npx playwright install chromium`
from `frontend/` first. The tests use simulated identity and API responses;
the optional live API smoke test is skipped by default. GitHub Actions runs
the Python tests, Lambda package builds, frontend build and browser tests, and Terraform validation
on each pull request and push to `main`, without AWS credentials or deployment.
The Lambda packages are written under ignored `output/`.
The issuance package downloads pinned Linux wheels during its build.

## Existing AWS environment

The AWS region is `ap-south-1`. The configured CLI login profile is
`ccd-login`; the Terraform and Python profile is `ccd`. Use the project
developer identity, not the account owner, for routine checks. Confirm it
before any AWS change:

```powershell
aws login --profile ccd-login
aws sts get-caller-identity --profile ccd --query Arn --output text
```

The ARN must end in `user/ccd-developer`. Keep credentials and login codes out
of Git and chat.

The existing Terraform state has been migrated to a private, versioned S3
backend, and the manual GitHub deployment workflow is active on `main`. Its
`development` environment has the required private secrets. The first GitHub
apply succeeded on 2026-10-20 after confirming the existing state. Follow
[the GitHub deployment guide](docs/GITHUB_DEPLOYMENT.md) before a live update.
Do not trigger an apply against an empty or unverified state.

This repository does **not** contain Terraform state. A fresh clone should
initialize the configured S3 backend and verify the existing state before any
apply. Do not recreate the deployed
resources from an empty state.
Never use a fresh state to recreate the deployed certificate store or website.

The real administrator subject-to-organization assignments are kept in the
ignored `infrastructure/organizations.auto.tfvars`. A fresh setup can copy
[`organizations.auto.tfvars.example`](infrastructure/organizations.auto.tfvars.example)
and replace its example value privately. Missing assignments give view-only
access. Keep the original mappings when adding an administrator.

The notification subscription is optional in a fresh environment but active
in the existing one. In each new PowerShell window, set its variables once
before a full Terraform plan:

```powershell
$env:TF_VAR_notification_email = Read-Host 'Enter the existing administrator notification email'
$env:TF_VAR_notification_email_enabled = 'true'
terraform -chdir=infrastructure plan
```

The variables remain set within that window. Inspect every proposed action
before applying. In particular, investigate any certificate table or bucket
replacement, SNS subscription removal, or unexpected API/CloudFront change.
Saved plan files belong only in ignored `tmp/`; they can contain sensitive
values. Terraform state and generated PDFs must never be committed.

The public website uses a private frontend bucket and CloudFront origin
access control. Certificate PDFs use a separate private bucket. CloudWatch
log retention is 30 days. Administrator APIs require Cognito authentication
and server-side organization checks. Public verification exposes record
details and status, not PDF downloads or stored hashes.

## Synthetic development dataset

[`data/demo_students.csv`](data/demo_students.csv) contains 51 clearly labeled
demo students, 17 for each organization. The maintenance script creates
deterministic sample PDFs and metadata under ignored `output/demo-students/`.
It checks every local PDF/hash and refuses to replace differing files or
existing cloud records. It uses the `ccd-developer` identity for the one-time
development import, directly stores PDFs and records, and sends **no** SNS
notification emails. These are sample records, not real student credentials.

From the project root, preview and validate locally:

```powershell
.\.venv\Scripts\python.exe backend/prepare_demo_dataset.py
```

After reviewing the CSV and confirming the developer identity above, upload
the prepared sample records once (safe to retry after a partial failure):

```powershell
.\.venv\Scripts\python.exe backend/prepare_demo_dataset.py --apply
```

This writes 51 durable records and private PDFs to the existing development
account. It does not change Terraform state or infrastructure.
