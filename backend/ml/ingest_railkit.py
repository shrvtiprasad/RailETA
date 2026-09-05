from __future__ import annotations

import argparse
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is declared in requirements.txt
    load_dotenv = None  # type: ignore[assignment]

from .railkit import RailKitHistoryClient, merge_events, normalize_history


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch one real RailKit history journey into the ML event CSV.")
    parser.add_argument("--train", required=True, help="Indian Railways train number")
    parser.add_argument("--date", required=True, help="Journey date as YYYY-MM-DD or DD-MM-YYYY")
    parser.add_argument(
        "--events",
        type=Path,
        default=_repo_root() / "backend" / "data" / "processed" / "running_events.csv",
        help="Normalized event CSV output path",
    )
    parser.add_argument("--cache-dir", type=Path, default=None, help="Raw RailKit response cache directory")
    parser.add_argument("--force", action="store_true", help="Refresh the cached journey and spend one API request")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    backend_env = _repo_root() / "backend" / ".env"
    if load_dotenv is not None:
        load_dotenv(backend_env, override=False)

    client = RailKitHistoryClient(cache_dir=args.cache_dir)
    payload = client.fetch_history(args.train, args.date, force=args.force)
    records = normalize_history(payload, args.train, args.date)
    if not records:
        raise RuntimeError("RailKit returned no station events; the event CSV was not changed.")
    count = merge_events(args.events, records)
    print(f"Imported {count} RailKit station events into {args.events}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"RailKit import stopped: {exc}")
        raise SystemExit(1) from exc
