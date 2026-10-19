"""Build a CycloneDX SBOM for the locked CPython 3.12 Linux wheel set."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from email.parser import Parser
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
WHEELHOUSE = ROOT / "work" / "lock-wheels"
OUTPUT = ROOT / "docs" / "sbom-python-cp312-linux-x86_64.cdx.json"
DIRECT_REQUIREMENTS = ROOT / "server" / "requirements.txt"
EXCLUDED = {"tzdata"}  # Windows-only marker in requirements.lock.
PACKAGING_WHEEL = next(WHEELHOUSE.glob("packaging-*.whl"), None)
if PACKAGING_WHEEL is None:
    raise SystemExit(f"Falta packaging en el wheelhouse: {WHEELHOUSE}")
sys.path.insert(0, str(PACKAGING_WHEEL))
from packaging.markers import default_environment
from packaging.requirements import Requirement
LICENSES = {
    "asgiref": "BSD-3-Clause",
    "cffi": "MIT-0",
    "cryptography": "Apache-2.0 OR BSD-3-Clause",
    "django": "BSD-3-Clause",
    "djangorestframework": "BSD-3-Clause",
    "gunicorn": "MIT",
    "lxml": "BSD-3-Clause",
    "packaging": "Apache-2.0 OR BSD-2-Clause",
    "psycopg": "LGPL-3.0-only",
    "psycopg-binary": "LGPL-3.0-only",
    "pycparser": "BSD-3-Clause",
    "sqlparse": "BSD-3-Clause",
    "typing-extensions": "PSF-2.0",
    "whitenoise": "MIT",
}


def normalized(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def main() -> None:
    if not WHEELHOUSE.is_dir():
        raise SystemExit(f"No existe el wheelhouse resuelto: {WHEELHOUSE}")
    environment = default_environment()
    environment.update({"sys_platform": "linux", "platform_machine": "x86_64", "python_version": "3.12", "python_full_version": "3.12.0", "platform_python_implementation": "CPython", "implementation_name": "cpython"})
    direct: dict[str, set[str]] = {}
    for line in DIRECT_REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate(environment):
            continue
        direct[normalized(requirement.name)] = set(requirement.extras)

    components = []
    purls: dict[str, str] = {}
    metadata_by_name = {}
    wheels_by_name = {}
    for wheel in sorted(WHEELHOUSE.glob("*.whl")):
        with ZipFile(wheel) as archive:
            metadata_path = next(
                (name for name in archive.namelist() if name.endswith(".dist-info/METADATA")),
                None,
            )
            if metadata_path is None:
                raise SystemExit(f"Falta METADATA: {wheel.name}")
            metadata = Parser().parsestr(archive.read(metadata_path).decode("utf-8"))
        name = normalized(metadata["Name"])
        if name in EXCLUDED:
            continue
        version = metadata["Version"]
        license_expression = LICENSES.get(name)
        if not license_expression:
            raise SystemExit(f"Agrega la licencia revisada de {name} a {Path(__file__).name}")
        purl = f"pkg:pypi/{name}@{version}"
        component = {
            "type": "library",
            "bom-ref": purl,
            "name": metadata["Name"],
            "version": version,
            "purl": purl,
            "scope": "required",
            "licenses": [{"expression": license_expression}],
            "hashes": [{"alg": "SHA-256", "content": hashlib.sha256(wheel.read_bytes()).hexdigest()}],
            "properties": [
                {"name": "redmagna:wheel", "value": wheel.name},
                {"name": "redmagna:runtime", "value": "CPython 3.12; Linux x86_64; manylinux_2_17"},
            ],
        }
        components.append(component)
        purls[name] = purl
        metadata_by_name[name] = metadata
        wheels_by_name[name] = wheel

    root_refs = sorted(purls[name] for name in direct if name in purls)
    if set(direct) - set(purls):
        raise SystemExit(f"No se encontró wheel Linux para: {', '.join(sorted(set(direct) - set(purls)))}")
    dependency_graph = [{"ref": "urn:redmagna:erp:python-runtime:unreleased", "dependsOn": root_refs}]
    for name in sorted(metadata_by_name):
        requirements = []
        for raw in metadata_by_name[name].get_all("Requires-Dist", []):
            requirement = Requirement(raw)
            candidate_extras = direct.get(name, set()) | {""}
            if requirement.marker and not any(requirement.marker.evaluate({**environment, "extra": extra}) for extra in candidate_extras):
                continue
            dependency_name = normalized(requirement.name)
            if dependency_name in purls:
                requirements.append(purls[dependency_name])
        dependency_graph.append({"ref": purls[name], "dependsOn": sorted(set(requirements))})

    if not components or not root_refs:
        raise SystemExit("No se encontraron componentes o dependencias directas.")
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": "urn:uuid:9ff6ca7f-245e-49d8-9b9c-0c6af8f04101",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "tools": {"components": [{"type": "application", "name": "Redmagna SBOM builder", "version": "1"}]},
            "component": {
                "type": "application",
                "bom-ref": "urn:redmagna:erp:python-runtime:unreleased",
                "name": "Redmagna ERP Python runtime",
                "version": "unreleased",
                "licenses": [{"expression": "AGPL-3.0-only"}],
                "properties": [
                    {"name": "redmagna:scope", "value": "Locked Python wheels for CPython 3.12 Linux x86_64; excludes base images and native wheel notices."},
                    {"name": "redmagna:lockfile", "value": "server/requirements.lock"},
                ],
            },
        },
        "components": components,
        "dependencies": dependency_graph,
    }
    OUTPUT.write_text(json.dumps(bom, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{OUTPUT.relative_to(ROOT)}: {len(components)} componentes, {len(root_refs)} dependencias directas")


if __name__ == "__main__":
    main()
