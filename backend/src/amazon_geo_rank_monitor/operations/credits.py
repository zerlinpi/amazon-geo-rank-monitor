"""Credit administration for operators with direct access to the deployment host."""

from __future__ import annotations

import argparse
import json

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from amazon_geo_rank_monitor.config import AppSettings
from amazon_geo_rank_monitor.repositories.billing_repository import BillingRepository


def credits_main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage workspace credits using DATABASE_URL; host access required",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="Find workspace IDs, optionally by member email")
    listing.add_argument("--email")
    listing.add_argument("--limit", type=int, default=100)
    show = commands.add_parser("show", help="Show balance and the latest 100 ledger entries")
    show.add_argument("--workspace", required=True)
    adjust = commands.add_parser("adjust", help="Preview a change; add --apply to commit it")
    adjust.add_argument("--workspace", required=True)
    amount = adjust.add_mutually_exclusive_group(required=True)
    amount.add_argument("--delta", type=int)
    amount.add_argument("--set-balance", type=int)
    adjust.add_argument("--operator", required=True, help="Operator label retained in the ledger")
    adjust.add_argument("--reason", required=True)
    adjust.add_argument(
        "--request-id", required=True, help="Unique ID; reuse only for an exact retry",
    )
    adjust.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = AppSettings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    repo = BillingRepository(engine)
    try:
        if args.command == "list":
            payload = repo.list_accounts(email=args.email, limit=args.limit)
        elif args.command == "show":
            payload = {
                **repo.account_details(args.workspace), "billing_mode": settings.billing_mode,
                "ledger": repo.list_ledger(owner_id=args.workspace),
            }
        else:
            payload = repo.adjust_balance(
                owner_id=args.workspace, delta=args.delta, balance=args.set_balance,
                operator=args.operator, reason=args.reason, request_id=args.request_id,
                apply=args.apply,
            )
    except (ValueError, KeyError) as exc:
        parser.exit(2, f"{exc}\n")
    except SQLAlchemyError:
        parser.exit(2, "Credit operation failed; check database connectivity and run migrations.\n")
    finally:
        engine.dispose()
    print(json.dumps(payload, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    credits_main()
