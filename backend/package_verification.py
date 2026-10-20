"""Build the small Lambda ZIP. Boto3 is supplied by the Lambda Python runtime."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def build_package(root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as bundle:
        for name in ("lambda_verify.py", "verification.py", "admin_auth.py", "organizations.py"):
            entry = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            bundle.writestr(entry, (root / "backend" / name).read_bytes())


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    package_path = project_root / "output" / "lambda" / "verification.zip"
    build_package(project_root, package_path)
    print(f"Lambda package ready: {package_path}")
