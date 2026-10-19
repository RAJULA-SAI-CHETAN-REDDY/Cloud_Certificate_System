# GitHub deployment for the existing development environment

The existing development and bootstrap Terraform states were migrated to the
private versioned S3 bucket on 2026-10-20. The GitHub workflow is **not active
yet**: the private environment secrets and a reviewed pull request are still
needed. Do not run a GitHub apply before those steps are complete.

## Order of work

1. The GitHub repository has a `development` environment restricted to branch
   `main`. Confirm that restriction before creating the AWS role. Add required
   reviewers if an eligible separate reviewer is available.
2. The one-time bootstrap created the GitHub OIDC provider, deploy role, and
   private state bucket. It attached five existing customer managed policies
   and mirrored the two relevant developer inline policies onto the role.
   The developer user's policies were not replaced. Keep the bootstrap
   configuration and state; do not repeat the initial apply.
3. Both Terraform states are in S3. The bootstrap state lists 17 resources;
   the development state lists all 80 original resources, including the
   certificate bucket, DynamoDB table, distribution, and API. Private,
   hash-verified pre-migration backups remain in ignored `tmp/state-backups`.
   On a fresh clone, `terraform init` connects to the existing remote state;
   do not create a new state or import those resources again.
4. In GitHub's `development` environment, set private secrets
   `ADMIN_ORGANIZATIONS_JSON` (the existing administrator subject-to-organization
   JSON mapping) and `NOTIFICATION_EMAIL` (the existing subscriber address).
   Do not paste either value into chat, code, logs, or a pull request.
5. With `AWS_PROFILE=ccd`, set the existing notification email input in your
   PowerShell session and inspect a **full** local Terraform plan. A
   post-migration plan on 2026-10-20 proposed only two Lambda updates: one
   changed package hash and one environment sensitivity marking. Review any
   new differences before GitHub deployment. The first GitHub run should
   be **plan**. Review it, then run **apply** with confirmation `DEPLOY`.

The workflow is manual and runs only from `main` in the `development`
environment. It checks the existing state before planning and blocks changes
to the certificate and frontend storage resources and other unexpected
deletions. A successful GitHub plan is not evidence of an applied deployment.
The state bucket and GitHub role are a small additional AWS footprint; keep
one development environment.

## Local commands after migration

Open PowerShell in the project root. Confirm the identity first:

```powershell
aws login --profile ccd-login
aws sts get-caller-identity --profile ccd --query Arn --output text
$env:AWS_PROFILE = 'ccd'
$env:TF_VAR_notification_email = Read-Host 'Enter the existing administrator notification email'
$env:TF_VAR_notification_email_enabled = 'true'
terraform -chdir=infrastructure plan
```

The ARN must end in `user/ccd-developer`. Stop if the state is missing or the
plan would replace an existing storage resource. The private organization map
must remain in the ignored `infrastructure/organizations.auto.tfvars` locally.
