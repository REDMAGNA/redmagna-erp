"""Pin the bundled SAT XSD/XSLT resources by SHA-256 for reproducible builds."""

from hashlib import sha256
from pathlib import Path
import argparse
import sys


ROOT = Path(__file__).resolve().parent.parent
SAT_ROOT = ROOT / "server" / "billing" / "fiscal" / "sat"
MANIFEST = SAT_ROOT / "SHA256SUMS.txt"
RESOURCE_SUFFIXES = {".xsd", ".xslt"}


def resource_paths():
    return sorted(
        path for path in SAT_ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in RESOURCE_SUFFIXES
    )


def manifest_text(paths):
    rows = []
    for path in paths:
        digest = sha256(path.read_bytes()).hexdigest()
        relative = path.relative_to(ROOT).as_posix()
        rows.append(f"{digest}  {relative}")
    return "\n".join(rows) + "\n"


def verify(paths):
    expected_paths = {path.relative_to(ROOT).as_posix() for path in paths}
    if not MANIFEST.is_file():
        raise ValueError(f"No existe el manifiesto SAT: {MANIFEST.relative_to(ROOT)}")

    recorded = {}
    for line_number, raw_line in enumerate(MANIFEST.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        parts = raw_line.split("  ", 1)
        if len(parts) != 2 or len(parts[0]) != 64 or any(char not in "0123456789abcdef" for char in parts[0]):
            raise ValueError(f"Formato inválido en {MANIFEST.relative_to(ROOT)}:{line_number}")
        digest, relative = parts
        if relative in recorded:
            raise ValueError(f"Ruta repetida en manifiesto: {relative}")
        recorded[relative] = digest

    if set(recorded) != expected_paths:
        missing = sorted(expected_paths - set(recorded))
        stale = sorted(set(recorded) - expected_paths)
        raise ValueError(f"Conjunto SAT distinto al manifiesto; faltan={missing}, sobrantes={stale}")

    changed = []
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        actual = sha256(path.read_bytes()).hexdigest()
        if actual != recorded[relative]:
            changed.append(relative)
    if changed:
        raise ValueError(f"Los recursos SAT no coinciden con SHA256SUMS.txt: {changed}")


def main():
    parser = argparse.ArgumentParser(description="Verifica los hashes de recursos SAT incluidos en Redmagna ERP.")
    parser.add_argument("--refresh", action="store_true", help="actualiza SHA256SUMS.txt tras revisar manualmente las fuentes SAT")
    args = parser.parse_args()
    paths = resource_paths()
    if not paths:
        raise SystemExit("No se encontraron XSD/XSLT SAT para verificar.")
    try:
        if args.refresh:
            MANIFEST.write_text(manifest_text(paths), encoding="utf-8", newline="\n")
            print(f"Manifiesto actualizado: {MANIFEST.relative_to(ROOT)} ({len(paths)} recursos)")
        else:
            verify(paths)
            print(f"Recursos SAT verificados: {len(paths)}")
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
