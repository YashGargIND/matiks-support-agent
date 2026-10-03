from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from support.channels.base import load_adapters
from support.channels.file import FileAdapter
from support.config import ROOT
from support.metrics import metrics
from support.pipeline import ingest, process
from support.store import Store


def main():
    parser = argparse.ArgumentParser(description="Matiks dry-run support workbench")
    parser.add_argument(
        "command",
        choices=["init", "ingest", "import", "process", "metrics", "run", "inspect-schema"],
    )
    parser.add_argument("path", nargs="?", help="JSON/CSV ticket export for import")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    store = Store()
    if args.command == "inspect-schema":
        from support.data import MongoReader

        reader = None
        try:
            reader = MongoReader()
            print(json.dumps(reader.inspect(), indent=2))
        except Exception as error:
            print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
            raise SystemExit(1)
        finally:
            if reader is not None:
                reader.close()
    if args.command == "import":
        if not args.path:
            parser.error("import requires an export path")
        print(json.dumps(ingest(store, FileAdapter(Path(args.path)))))
    if args.command in {"ingest", "run"}:
        adapters = load_adapters()
        if not adapters:
            print("No channels enabled. Configure channels in config.yaml or import a real export.")
        for adapter in adapters:
            try:
                print(json.dumps(ingest(store, adapter)))
            except Exception as error:
                # Never print provider errors containing raw ticket bodies or secrets.
                print(
                    json.dumps(
                        {
                            "channel": adapter.name,
                            "status": "failed",
                            "error_type": type(error).__name__,
                        }
                    )
                )
    if args.command in {"process", "run"}:
        for ticket in [t for t in store.tickets() if t.status == "open"][: max(0, args.limit)]:
            asyncio.run(process(store, ticket.id))
        print(json.dumps(metrics(store), indent=2))
    if args.command == "metrics":
        print(json.dumps(metrics(store), indent=2))
    if args.command == "init":
        print("Local store initialized. All action modes are dry_run.")
    if args.command == "run":
        os.execv(
            str(ROOT / ".venv/bin/streamlit"),
            [
                "streamlit",
                "run",
                str(ROOT / "dashboard.py"),
                "--server.address=127.0.0.1",
                "--server.headless=true",
                "--server.port=8507",
                "--browser.gatherUsageStats=false",
            ],
        )
