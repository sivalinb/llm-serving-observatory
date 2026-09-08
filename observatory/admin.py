"""Operator-only CLI. Run on the VM; there is intentionally no public admin API."""

import argparse
import json
import os

from .assistant_store import AssistantStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.getenv("ASSISTANT_DB", "data/assistant.sqlite"))
    commands = parser.add_subparsers(dest="command", required=True)
    invite = commands.add_parser("invite")
    invite.add_argument("--tokens", type=int, default=100000)
    invite.add_argument("--requests", type=int, default=20)
    invite.add_argument("--hours", type=float, default=24)
    revoke = commands.add_parser("revoke")
    revoke.add_argument("user_id")
    backup = commands.add_parser("backup")
    backup.add_argument("destination")
    args = parser.parse_args()
    store = AssistantStore(args.db)
    try:
        if args.command == "invite":
            print(store.invite(args.tokens, args.requests, args.hours))
        elif args.command == "revoke":
            print(json.dumps({"keys_revoked": store.revoke(args.user_id)}))
        elif args.command == "backup":
            store.backup(args.destination)
            print("Backup created and integrity checked; protect it as credential material.")
    finally:
        store.close()


if __name__ == "__main__":
    main()
