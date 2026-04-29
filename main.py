from __future__ import annotations

import argparse
import json

from app.db import init_db
from app.server import run_server
from app.services import ask_agent, import_export_file, list_groups, list_import_batches, search_messages


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WhatsApp Agent MVP")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create the SQLite database schema")
    sub.add_parser("serve", help="Run the local HTTP server")

    import_cmd = sub.add_parser("import", help="Import a WhatsApp export text file")
    import_cmd.add_argument("file_path")
    import_cmd.add_argument("--group", required=True, dest="group_name")
    import_cmd.add_argument("--source-owner")

    search_cmd = sub.add_parser("search", help="Search imported messages")
    search_cmd.add_argument("--q")
    search_cmd.add_argument("--group")
    search_cmd.add_argument("--sender")
    search_cmd.add_argument("--date-from")
    search_cmd.add_argument("--date-to")
    search_cmd.add_argument("--limit", type=int, default=10)

    ask_cmd = sub.add_parser("ask", help="Ask the deterministic agent")
    ask_cmd.add_argument("question")
    ask_cmd.add_argument("--group")
    ask_cmd.add_argument("--sender")
    ask_cmd.add_argument("--date-from")
    ask_cmd.add_argument("--date-to")
    ask_cmd.add_argument("--limit", type=int, default=8)

    sub.add_parser("groups", help="List groups")
    sub.add_parser("imports", help="List import batches")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.command == "init-db":
        init_db()
        print("Database initialized.")
        return

    if args.command == "serve":
        init_db()
        run_server()
        return

    if args.command == "import":
        result = import_export_file(args.file_path, group_name=args.group_name, source_owner=args.source_owner)
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
        return

    if args.command == "search":
        rows = search_messages(
            q=args.q,
            group_name=args.group,
            sender=args.sender,
            date_from=args.date_from,
            date_to=args.date_to,
            limit=args.limit,
        )
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    if args.command == "ask":
        result = ask_agent(
            question=args.question,
            group_name=args.group,
            sender=args.sender,
            date_from=args.date_from,
            date_to=args.date_to,
            limit=args.limit,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "groups":
        print(json.dumps(list_groups(), ensure_ascii=False, indent=2))
        return

    if args.command == "imports":
        print(json.dumps(list_import_batches(), ensure_ascii=False, indent=2))
        return


if __name__ == "__main__":
    main()
