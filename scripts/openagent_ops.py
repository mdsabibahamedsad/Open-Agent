#!/usr/bin/env python3
"""MP26: OpenAgent operations CLI (self-hosted first, no cloud required).

Wraps the operations + platform APIs; respects auth and permissions.

Examples:
    python scripts/openagent_ops.py --org <org-id> health
    python scripts/openagent_ops.py alerts
    python scripts/openagent_ops.py incidents
    python scripts/openagent_ops.py audit --action workflow.execute
    python scripts/openagent_ops.py workers
    python scripts/openagent_ops.py regions
    python scripts/openagent_ops.py diagnostics
    python scripts/openagent_ops.py status
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
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="openagent_ops",
                                     description="OpenAgent operations")
    parser.add_argument("--api", default=os.getenv("API_BASE", "http://localhost:8000/api/v1"))
    parser.add_argument("--api-key", default=os.getenv("OPENAGENT_API_KEY", ""))
    parser.add_argument("--org", default=os.getenv("OPENAGENT_ORG_ID", ""))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="platform health summary")
    sub.add_parser("health", help="unified operational health")
    sub.add_parser("alerts", help="list alerts")
    sub.add_parser("incidents", help="list incidents")
    sub.add_parser("workers", help="cloud worker fleet")
    sub.add_parser("queues", help="queue depths")
    sub.add_parser("regions", help="region health")
    sub.add_parser("diagnostics", help="run self-hosted diagnostics")
    sub.add_parser("deployments", help="deployment history")
    audit = sub.add_parser("audit", help="organization audit trail")
    audit.add_argument("--action", default="")
    audit.add_argument("--resource", default="")

    args = parser.parse_args(argv)
    routes = {
        "status": "/operations/health",
        "health": "/operations/health",
        "alerts": "/operations/alerts",
        "incidents": "/operations/incidents",
        "workers": "/cloud/workers",
        "queues": "/cloud/queues",
        "regions": "/cloud/regions",
        "diagnostics": "/operations/diagnostics",
        "deployments": "/operations/deployments",
    }
    if args.command == "audit":
        path = "/operations/audit"
        query = "&".join(f"{k}={v}" for k, v in
                         (("action", args.action), ("resource", args.resource)) if v)
        out = _call(args.api, f"{path}?{query}" if query else path,
                    api_key=args.api_key, org=args.org)
    else:
        out = _call(args.api, routes[args.command],
                    api_key=args.api_key, org=args.org)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
