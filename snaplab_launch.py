"""PyInstaller entry script.

PyInstaller treats its target file as a top-level script, so the package's
own ``__main__`` (which uses relative imports) doesn't work as the entry
point. This thin wrapper imports the package normally and invokes the same
main() that ``python -m snaplab`` would call.
"""
from __future__ import annotations

import sys


def main() -> int:
    from snaplab.__main__ import main as _main

    return _main()


if __name__ == "__main__":
    raise SystemExit(main())
