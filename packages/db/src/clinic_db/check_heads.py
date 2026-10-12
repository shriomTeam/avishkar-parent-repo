"""CI guard: two teams merging migrations in parallel creates two Alembic heads.

Fails with instructions instead of letting `alembic upgrade head` break later.
"""

import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def main() -> int:
    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    if len(heads) > 1:
        print(f"Multiple migration heads: {heads}")
        print("Rebase your branch and set down_revision to the current head, or run:")
        print('  cd packages/db && uv run alembic merge heads -m "merge"')
        return 1
    print(f"OK: single migration head {heads[0] if heads else '(none)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
