from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "source.zip"
INCLUDE_FILES = [".dockerignore", ".env.example", ".gitignore", "CHANGELOG.md", "Dockerfile", "LICENSE", "README.md", "SECURITY.md", "docker-compose.yml"]
INCLUDE_DIRS = ["server", "dist", "docs", "tools"]
SENSITIVE_SUFFIXES = {".cer", ".crt", ".key", ".pem", ".p12", ".pfx"}


def is_sensitive_file(path):
    name = path.name.lower()
    return (
        "secrets" in {part.lower() for part in path.parts}
        or path.suffix.lower() in SENSITIVE_SUFFIXES
        or name == "csd_password"
        or name == ".env"
        or (name.startswith(".env.") and name != ".env.example")
    )


def main():
    with ZipFile(OUTPUT, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in INCLUDE_FILES:
            path = ROOT / relative
            if path.is_file():
                archive.write(path, relative)
        for relative in INCLUDE_DIRS:
            base = ROOT / relative
            for path in sorted(base.rglob("*")):
                if not path.is_file() or "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"} or is_sensitive_file(path):
                    continue
                if path.relative_to(ROOT).as_posix() in {"dist/license.txt", "dist/source.zip"}:
                    continue
                archive.write(path, path.relative_to(ROOT).as_posix())
    print(f"Source archive created: {OUTPUT}")


if __name__ == "__main__":
    main()
