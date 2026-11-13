#!/usr/bin/env python3
"""Verificador de integridade SHA-256 e conformidade JSON Schema para contracts/."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "contracts" / "schemas"
FIXTURES_DIR = ROOT / "contracts" / "fixtures"
EXAMPLES_DIR = ROOT / "contracts" / "examples"


def build_schema_registry() -> tuple[Registry, dict[str, dict]]:
    schemas: dict[str, dict] = {}
    resources = []
    for schema_path in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        schemas[schema_path.name] = schema
        schema_id = schema.get("$id", schema_path.name)
        resource = Resource.from_contents(schema)
        resources.append((schema_id, resource))
        resources.append((schema_path.name, resource))
    registry = Registry().with_resources(resources)
    return registry, schemas


def validate_with_schema(instance: dict, schema_name: str, registry: Registry, schemas: dict[str, dict]) -> None:
    schema = schemas[schema_name]
    validator = Draft202012Validator(schema, registry=registry)
    validator.validate(instance)


def verify_checksums() -> list[str]:
    checksum_file = FIXTURES_DIR / "checksums.sha256"
    if not checksum_file.exists():
        raise FileNotFoundError(f"Arquivo de checksum ausente: {checksum_file}")

    verified: list[str] = []
    for raw_line in checksum_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        expected_hash, filename = line.split(None, 1)
        filename = filename.strip()
        target = FIXTURES_DIR / filename
        if not target.exists():
            raise FileNotFoundError(f"Fixture listada no checksum não encontrada: {target}")
        actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(
                f"SHA-256 mismatch em {filename}: esperado {expected_hash}, obtido {actual_hash}"
            )
        verified.append(filename)
    return verified


def main() -> int:
    registry, schemas = build_schema_registry()
    print(f"[F9-VERIFY] {len(schemas)} schemas JSON Draft 2020-12 válidos.")

    verified_fixtures = verify_checksums()
    for fname in verified_fixtures:
        data = json.loads((FIXTURES_DIR / fname).read_text(encoding="utf-8"))
        validate_with_schema(data, "golden_fixture.schema.json", registry, schemas)
        print(f"[F9-VERIFY] Fixture {fname}: SHA-256 OK + golden_fixture.schema.json OK.")

    example_map = {
        "rpc_request_lqr.json": "rpc_request.schema.json",
        "rpc_response_lqr.json": "rpc_response.schema.json",
        "statespace_example.json": "state_space.schema.json",
        "pvm_skeleton.json": "pvm.schema.json",
    }
    for ex_name, schema_name in example_map.items():
        ex_path = EXAMPLES_DIR / ex_name
        ex_data = json.loads(ex_path.read_text(encoding="utf-8"))
        validate_with_schema(ex_data, schema_name, registry, schemas)
        print(f"[F9-VERIFY] Exemplo {ex_name} validado contra {schema_name}.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
