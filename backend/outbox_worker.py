"""Manually run one batch of outbox event normalization and validation."""

import argparse
import logging

from database import SessionLocal
from event_processing import process_event_batch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--lease-seconds", type=int, default=300)
    args = parser.parse_args()
    if args.batch_size < 1 or args.lease_seconds < 1:
        parser.error("batch size and lease seconds must be positive")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = process_event_batch(
        SessionLocal, batch_size=args.batch_size, lease_seconds=args.lease_seconds
    )
    print(
        f"Outbox batch complete: claimed={result.claimed}, "
        f"processed={result.processed}, failed={result.failed}"
    )
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
