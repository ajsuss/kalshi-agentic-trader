#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.migration.legacy_compat import LegacyCompat


def main() -> None:
    compat = LegacyCompat(repo_root=REPO_ROOT)
    snapshot = compat.build_step45_team_status_snapshot()
    print(json.dumps(snapshot, indent=2))


if __name__ == "__main__":
    main()
