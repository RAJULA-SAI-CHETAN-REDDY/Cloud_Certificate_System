"""Build a Linux x86_64 Python 3.12 Lambda package from binary wheels."""

import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / "output" / "lambda" / "issuance.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ccd-issuance-") as directory:
        package = Path(directory)
        subprocess.run([sys.executable, "-m", "pip", "install", "--platform", "manylinux2014_x86_64",
            "--implementation", "cp", "--python-version", "3.12", "--only-binary=:all:",
            "--target", str(package), "-r", str(ROOT / "backend" / "issuance-requirements.txt")], check=True)
        for name in ("lambda_issue.py", "admin_auth.py", "organizations.py", "generate_certificate.py", "notifications.py", "management.py", "verification.py"):
            (package / name).write_bytes((ROOT / "backend" / name).read_bytes())
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as bundle:
            for path in sorted(package.rglob("*")):
                if (path.is_file() and "__pycache__" not in path.parts
                        and path.suffix not in (".pyc", ".exe", ".pyd", ".dll")
                        and not (path.name == "RECORD" and path.parent.name.endswith(".dist-info"))
                        and path.relative_to(package).parts[0] not in ("bin", "Scripts")):
                    entry = ZipInfo(path.relative_to(package).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
                    entry.compress_type = ZIP_DEFLATED
                    entry.external_attr = 0o644 << 16
                    bundle.writestr(entry, path.read_bytes())
    print(f"Issuance Lambda package ready: {output}")


if __name__ == "__main__":
    main()
