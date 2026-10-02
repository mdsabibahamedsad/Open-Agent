#!/usr/bin/env python3
"""MP25: OpenAgent cloud operations CLI.

Respects authentication (API key + org id) and permissions; every call
is a thin wrapper over the service-authenticated HTTP API.

Examples:
    python scripts/openagent_cloud.py --api http://localhost:8000/api/v1 \
        --org <org-id> status
    python scripts/openagent_cloud.py workers --region local-1
    python scripts/openagent_cloud.py queues
    python scripts/openagent_cloud.py executions submit --class workflow
    python scripts/openagent_cloud.py regions
    python scripts/openagent_cloud.py storage
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request


def _headers(api_key: str, org: str) -> dict:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if org:
        headers["X-Organization-ID"] = org
    return headers


def _call(api: str, path: str, *, method="GET", body=None,
          api_key="", org="") -> object:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(api.rstrip("/") + path, data=data,
                                     headers=_headers(api_key, org),
                                     method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode()
            return json.loads(payload) if payload else {}
    except Exception as exc:  # urllib raises URLError/HTTPError
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="openagent_cloud",
                                     description="OpenAgent cloud operations")
    parser.add_argument("--api", default=os.getenv("API_BASE", "http://localhost:8000/api/v1"))
    parser.add_argument("--api-key", default=os.getenv("OPENAGENT_API_KEY", ""))
    parser.add_argument("--org", default=os.getenv("OPENAGENT_ORG_ID", ""))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="platform health + incident mode")
    workers = sub.add_parser("workers", help="list workers")
    workers.add_argument("--region", default="")
    workers.add_argument("--pool", default="")
    sub.add_parser("queues", help="queue depths + DLQ counts")
    sub.add_parser("regions", help="list regions")
    sub.add_parser("storage", help="storage usage overview")
    sub.add_parser("usage", help="metered usage by meter")

    exe = sub.add_parser("executions", help="execution operations")
    exe_sub = exe.add_subparsers(dest="op", required=True)
    submit = exe_sub.add_parser("submit", help="submit an execution")
    submit.add_argument("--class", dest="execution_class", default="workflow")
    exe_get = exe_sub.add_parser("get", help="describe an execution")
    exe_get.add_argument("execution_id")
    exe_cancel = exe_sub.add_parser("cancel", help="cancel an execution")
    exe_cancel.add_argument("execution_id")
    exe_retry = exe_sub.add_parser("retry", help="retry an execution")
    exe_retry.add_argument("execution_id")
    exe_events = exe_sub.add_parser("events", help="list execution events")
    exe_events.add_argument("execution_id")

    args = parser.parse_args(argv)
    out: object
    if args.command == "status":
        out = _call(args.api, "/cloud/health", api_key=args.api_key, org=args.org)
    elif args.command == "workers":
        query = ""
        if args.region:
            query += f"?region={args.region}"
        out = _call(args.api, f"/cloud/workers{query}", api_key=args.api_key, org=args.org)
    elif args.command == "queues":
        out = _call(args.api, "/cloud/queues", api_key=args.api_key, org=args.org)
    elif args.command == "regions":
        out = _call(args.api, "/cloud/regions", api_key=args.api_key, org=args.org)
    elif args.command == "storage":
        out = _call(args.api, "/cloud/storage", api_key=args.api_key, org=args.org)
    elif args.command == "usage":
        out = _call(args.api, "/cloud/usage", api_key=args.api_key, org=args.org)
    elif args.command == "executions":
        if args.op == "submit":
            out = _call(args.api, "/cloud/executions", method="POST",
                        body={"execution_class": args.execution_class},
                        api_key=args.api_key, org=args.org)
        elif args.op == "get":
            out = _call(args.api, f"/cloud/executions/{args.execution_id}",
                        api_key=args.api_key, org=args.org)
        elif args.op == "cancel":
            out = _call(args.api, f"/cloud/executions/{args.execution_id}/cancel",
                        method="POST", body={}, api_key=args.api_key, org=args.org)
        elif args.op == "retry":
            out = _call(args.api, f"/cloud/executions/{args.execution_id}/retry",
                        method="POST", body={}, api_key=args.api_key, org=args.org)
        else:
            out = _call(args.api, f"/cloud/executions/{args.execution_id}/events",
                        api_key=args.api_key, org=args.org)
    else:
        parser.print_help()
        return
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
