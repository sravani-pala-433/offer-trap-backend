"""Remove incomplete, unclaimed evidence uploads past their expiry time."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.services.evidence_service import cleanup_expired_uploads


def main() -> int:
    with SessionLocal() as session:
        deleted = cleanup_expired_uploads(session)
    print(f"Deleted {deleted} expired unclaimed upload(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
