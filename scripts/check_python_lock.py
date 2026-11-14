"""Verify an isolated environment exactly matches all pins and active dependency metadata."""

import argparse
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("lock", type=Path)
    args = parser.parse_args()
    pins = {}
    for line in args.lock.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        requirement = Requirement(line)
        specifiers = list(requirement.specifier)
        if requirement.marker or len(specifiers) != 1 or specifiers[0].operator != "==":
            raise ValueError(f"Expected unconditional exact pin: {line}")
        pins[canonicalize_name(requirement.name)] = specifiers[0].version
    installed = {
        canonicalize_name(dist.metadata["Name"]): dist.version for dist in metadata.distributions()
    }
    if pins != installed:
        raise ValueError(
            f"Environment/lock mismatch: missing={pins.keys() - installed.keys()}, extra={installed.keys() - pins.keys()}, different={[(name, version, installed.get(name)) for name, version in pins.items() if installed.get(name) != version]}"
        )
    count = 0
    for dist in metadata.distributions():
        for raw in dist.requires or []:
            requirement = Requirement(raw)
            if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                continue
            name = canonicalize_name(requirement.name)
            if name not in pins or pins[name] not in requirement.specifier:
                raise ValueError(
                    f"Unpinned or incompatible transitive requirement: {dist.name}: {raw}"
                )
            count += 1
    print(
        f"Exact lock closure PASS: {len(pins)} distributions and {count} active dependency edges, including pip."
    )


if __name__ == "__main__":
    main()
