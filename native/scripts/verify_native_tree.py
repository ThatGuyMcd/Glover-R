#!/usr/bin/env python3
"""Read-only native source verification using the assembler's shared contract."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from glover.native_contract import verify_native_workspace


def verify(root: Path) -> dict:
    return verify_native_workspace(root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.root), indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as error:
        print('NATIVE SOURCE CHECK FAILED: ' + str(error))
        raise SystemExit(1)
