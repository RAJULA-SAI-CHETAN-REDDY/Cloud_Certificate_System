"""Build the small Lambda ZIP. Boto3 is supplied by the Lambda Python runtime."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(__file__).resolve().parents[1]
output = root / "output" / "lambda" / "verification.zip"
output.parent.mkdir(parents=True, exist_ok=True)
with ZipFile(output, "w", compression=ZIP_DEFLATED) as bundle:
    for name in ("lambda_verify.py", "verification.py", "admin_auth.py", "organizations.py"):
        bundle.write(root / "backend" / name, arcname=name)
print(f"Lambda package ready: {output}")
