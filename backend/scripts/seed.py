import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app import db  # noqa: E402


def main() -> None:
    db.init_db()
    try:
        counts = db.reseed_reference()
    except ValueError as exc:
        print(f"Seed failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print("Reference data loaded: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
