"""CLI for QuantLearn runtime monitoring (REQ-013).

Examples:
    python scripts/monitoring_check.py status
    python scripts/monitoring_check.py stale --max-age 300
    python scripts/monitoring_check.py event --component data.eastmoney --type data_fetch_failure --severity warn --message "timeout"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.monitoring import get_default_monitor  # noqa: E402


def cmd_status(args) -> int:
    mon = get_default_monitor()
    mon.ensure_tables()
    events = mon.recent_events(limit=args.limit, min_severity=args.min_severity)
    if not events:
        print("monitoring: no recent events")
        return 0
    for ev in events:
        target = f" {ev.strategy}" if ev.strategy else ""
        code = f" {ev.stock_code}" if ev.stock_code else ""
        print(f"{ev.created_at} [{ev.severity}] {ev.component}{target}{code} {ev.event_type}: {ev.message}")
    return 0


def cmd_stale(args) -> int:
    mon = get_default_monitor()
    events = mon.check_stale_components(max_age_seconds=args.max_age)
    if not events:
        print(f"monitoring: no stale components older than {args.max_age}s")
        return 0
    for ev in events:
        print(f"{ev.created_at} [{ev.severity}] {ev.message}")
    return 2


def cmd_event(args) -> int:
    ev = get_default_monitor().record_event(
        args.component,
        args.type,
        args.severity,
        args.message,
        strategy=args.strategy,
        stock_code=args.stock_code,
        details=args.details,
        alert=not args.no_alert,
    )
    print(f"recorded {ev.created_at} [{ev.severity}] {ev.component} {ev.event_type}: {ev.message}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QuantLearn monitoring CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="show recent monitoring events")
    p_status.add_argument("--limit", type=int, default=20)
    p_status.add_argument("--min-severity", default=None, choices=["info", "warn", "error", "critical"])
    p_status.set_defaults(func=cmd_status)

    p_stale = sub.add_parser("stale", help="alert on stale component heartbeats")
    p_stale.add_argument("--max-age", type=int, default=300)
    p_stale.set_defaults(func=cmd_stale)

    p_event = sub.add_parser("event", help="record a manual monitoring event")
    p_event.add_argument("--component", required=True)
    p_event.add_argument("--type", required=True)
    p_event.add_argument("--severity", default="warn", choices=["info", "warn", "error", "critical"])
    p_event.add_argument("--message", required=True)
    p_event.add_argument("--strategy", default="")
    p_event.add_argument("--stock-code", default="")
    p_event.add_argument("--details", default="")
    p_event.add_argument("--no-alert", action="store_true")
    p_event.set_defaults(func=cmd_event)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
