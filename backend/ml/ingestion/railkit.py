"""Compatibility CLI at the path defined by the RailETA data specification."""

from ..ingest_railkit import build_parser, main
from ..railkit import RailKitHistoryClient, merge_events, normalize_history

__all__ = [
    "RailKitHistoryClient",
    "merge_events",
    "normalize_history",
    "build_parser",
    "main",
]


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"RailKit import stopped: {exc}")
        raise SystemExit(1) from exc
