#!/usr/bin/env python3
"""MP27: OpenAgent enterprise security CLI.

Wraps the enterprise identity APIs; respects auth and permissions.

Examples:
    python scripts/openagent_security.py --org <org-id> status
    python scripts/openagent_security.py sso
    python scripts/openagent_security.py scim
    python scripts/openagent_security.py policies
    python scripts/openagent_security.py audit --method oidc
    python scripts/openagent_security.py diagnostics
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
    parser = argparse.ArgumentParser(prog="openagent_security",
                                     description="OpenAgent enterprise security")
    parser.add_argument("--api", default=os.getenv("API_BASE", "http://localhost:8000/api/v1"))
    parser.add_argument("--api-key", default=os.getenv("OPENAGENT_API_KEY", ""))
    parser.add_argument("--org", default=os.getenv("OPENAGENT_ORG_ID", ""))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="security posture summary")
    sub.add_parser("sso", help="SSO configurations")
    sub.add_parser("scim", help="SCIM credentials")
    sub.add_parser("policies", help="security policies")
    sub.add_parser("devices", help="user devices")
    sub.add_parser("controls", help="compliance controls")
    sub.add_parser("diagnostics", help="operations diagnostics")
    audit = sub.add_parser("audit", help="identity audit trail")
    audit.add_argument("--method", default="")

    args = parser.parse_args(argv)
    routes = {
        "status": "/enterprise/posture",
        "sso": "/enterprise/sso",
        "scim": "/enterprise/scim/credentials",
        "policies": "/enterprise/policies",
        "devices": "/enterprise/devices",
        "controls": "/enterprise/controls",
        "diagnostics": "/operations/diagnostics",
    }
    if args.command == "audit":
        path = "/enterprise/audit"
        if args.method:
            path += f"?method={args.method}"
        out = _call(args.api, path, api_key=args.api_key, org=args.org)
    else:
        out = _call(args.api, routes[args.command],
                    api_key=args.api_key, org=args.org)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
