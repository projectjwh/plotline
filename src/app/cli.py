"""Operator commands.

    python -m src.app.cli make-admin someone@example.com
    python -m src.app.cli revoke-admin someone@example.com
    python -m src.app.cli purge-claim-docs       # daily: delete claim documents 90 days after the decision

Admin rights are never granted at sign-up (emails are not verified), only here.
"""
from __future__ import annotations

import sys

from src.app.context import AppContext
from src.app.core.config import Settings


def main(argv: list[str]) -> int:
    if argv == ["purge-claim-docs"]:
        n = AppContext(Settings.from_env()).verification.purge_documents()
        print(f"purged documents of {n} decided claim(s)")
        return 0
    if len(argv) != 2 or argv[0] not in ("make-admin", "revoke-admin"):
        print(__doc__)
        return 2
    ctx = AppContext(Settings.from_env())
    u = ctx.identity.set_admin(argv[1], argv[0] == "make-admin")
    print(f"{u['email']}: is_admin={u['is_admin']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
