#!/usr/bin/env python3
"""OpenAgent commerce CLI — real, working commands for MP24 billing.

Server commands (need OPENAGENT_API_URL + OPENAGENT_API_KEY + org)::

    python scripts/openagent_commerce.py billing status
    python scripts/openagent_commerce.py billing usage --meter agent_runs \\
        --from 2026-09-01T00:00:00+00:00 --to 2026-10-01T00:00:00+00:00
    python scripts/openagent_commerce.py billing invoices
    python scripts/openagent_commerce.py registry list
    python scripts/openagent_commerce.py registry add --slug acme \\
        --name "Acme registry" --type PRIVATE --endpoint https://r.acme.example
    python scripts/openagent_commerce.py registry test <registry-id>
    python scripts/openagent_commerce.py registry sync <registry-id>
    python scripts/openagent_commerce.py publisher products --publisher <id>
    python scripts/openagent_commerce.py publisher revenue --publisher <id>
    python scripts/openagent_commerce.py publisher payouts --publisher <id>
    python scripts/openagent_commerce.py entitlements check --feature package.install

Every command talks to the real API; nothing is fabricated. Paid flows in
BILLING_MODE=disabled return an explicit COMMERCE_DISABLED error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def _api(method: str, path: str, params: dict | None = None,
         body: dict | None = None) -> tuple[int, str]:
    base = os.environ.get("OPENAGENT_API_URL", "http://localhost:8000").rstrip("/")
    org = os.environ["OPENAGENT_ORG_ID"]
    key = os.environ["OPENAGENT_API_KEY"]
    query = ("?" + urllib.parse.urlencode({k: v for k, v in (params or {}).items()
                                           if v is not None})) if params else ""
    url = f"{base}/api/v1{path}{query}"
    data = json.dumps(body or {}).encode() if body is not None or method != "GET" else None
    request = urllib.request.Request(url, data=data, method=method, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "X-Organization-ID": org,
    })
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def _require_server_env() -> bool:
    ok = True
    for name in ("OPENAGENT_API_KEY", "OPENAGENT_ORG_ID"):
        if not os.environ.get(name):
            print(f"error: {name} environment variable is required", file=sys.stderr)
            ok = False
    return ok


def _show(status: int, body: str) -> int:
    print(f"status={status}\n{body}")
    return 0 if status < 300 else 1


def cmd_billing_status(_args: argparse.Namespace) -> int:
    if not _require_server_env():
        return 1
    status, body = _api("GET", "/billing/status")
    if status >= 300:
        print(f"status={status}\n{body}", file=sys.stderr)
        return 1
    payload = json.loads(body)
    print(f"mode={payload.get('mode')} provider={payload.get('provider')} "
          f"configured={payload.get('configured')} "
          f"test_mode={payload.get('test_mode')}")
    return 0


def cmd_billing_usage(args: argparse.Namespace) -> int:
    if not _require_server_env():
        return 1
    status, body = _api("GET", "/usage/summary", {
        "meter": args.meter, "period_start": args.from_, "period_end": args.to})
    if status >= 300:
        print(f"status={status}\n{body}", file=sys.stderr)
        return 1
    payload = json.loads(body)
    print(f"meter={payload.get('meter')} total={payload.get('total')} "
          f"events={payload.get('events')} aggregation={payload.get('aggregation')}")
    return 0


def cmd_billing_invoices(_args: argparse.Namespace) -> int:
    if not _require_server_env():
        return 1
    status, body = _api("GET", "/invoices")
    if status >= 300:
        print(f"status={status}\n{body}", file=sys.stderr)
        return 1
    for item in json.loads(body).get("data", []):
        print(f"{item.get('id')}  {item.get('status')}  "
              f"{item.get('total_minor')} {item.get('currency')}")
    return 0


def cmd_registry_list(_args: argparse.Namespace) -> int:
    if not _require_server_env():
        return 1
    status, body = _api("GET", "/registries")
    if status >= 300:
        print(f"status={status}\n{body}", file=sys.stderr)
        return 1
    for item in json.loads(body).get("data", []):
        print(f"{item.get('slug')}  [{item.get('registry_type')}]  "
              f"trust={item.get('trust_level')} enabled={item.get('enabled')}  "
              f"{item.get('name')} ({item.get('id')})")
    return 0


def cmd_registry_add(args: argparse.Namespace) -> int:
    if not _require_server_env():
        return 1
    return _show(*_api("POST", "/registries", body={
        "slug": args.slug, "name": args.name, "registry_type": args.type,
        "endpoint": args.endpoint or "", "visibility": args.visibility,
        "trust_level": args.trust, "auth_type": args.auth,
        "credential_ref": args.credential_ref or ""}))


def cmd_registry_test(args: argparse.Namespace) -> int:
    if not _require_server_env():
        return 1
    return _show(*_api("POST", f"/registries/{args.registry_id}/test", body={}))


def cmd_registry_sync(args: argparse.Namespace) -> int:
    if not _require_server_env():
        return 1
    return _show(*_api("POST", f"/registries/{args.registry_id}/sync", body={}))


def cmd_publisher_products(args: argparse.Namespace) -> int:
    if not _require_server_env():
        return 1
    status, body = _api("GET", "/products")
    if status >= 300:
        print(f"status={status}\n{body}", file=sys.stderr)
        return 1
    for item in json.loads(body).get("data", []):
        print(f"{item.get('id')}  [{item.get('product_type')}/"
              f"{item.get('pricing_model')}] {item.get('status')}  "
              f"listing={item.get('listing_id')}")
    return 0


def cmd_publisher_revenue(args: argparse.Namespace) -> int:
    if not _require_server_env():
        return 1
    status, body = _api("GET", "/revenue", {"publisher_id": args.publisher})
    if status >= 300:
        print(f"status={status}\n{body}", file=sys.stderr)
        return 1
    payload = json.loads(body)
    print(f"balances={json.dumps(payload.get('balances', {}))}")
    for item in payload.get("data", []):
        print(f"{item.get('id')}  gross={item.get('gross_minor')}  "
              f"fee={item.get('fee_minor')} net={item.get('net_minor')}  "
              f"{item.get('currency')} [{item.get('status')}]")
    return 0


def cmd_publisher_payouts(args: argparse.Namespace) -> int:
    if not _require_server_env():
        return 1
    status, body = _api("GET", "/payouts", {"publisher_id": args.publisher})
    if status >= 300:
        print(f"status={status}\n{body}", file=sys.stderr)
        return 1
    for item in json.loads(body).get("data", []):
        print(f"{item.get('id')}  {item.get('status')}  "
              f"{item.get('amount_minor')} {item.get('currency')}")
    return 0


def cmd_entitlements_check(args: argparse.Namespace) -> int:
    if not _require_server_env():
        return 1
    status, body = _api("GET", "/entitlements/check",
                        {"feature": args.feature})
    if status >= 300:
        print(f"status={status}\n{body}", file=sys.stderr)
        return 1
    payload = json.loads(body)
    print(f"feature={payload.get('feature')} allowed={payload.get('allowed')} "
          f"reason={payload.get('reason')}")
    return 0 if payload.get("allowed") else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openagent-commerce",
                                     description="OpenAgent billing/commerce toolkit")
    sub = parser.add_subparsers(dest="command", required=True)

    billing = sub.add_parser("billing", help="billing status/usage/invoices")
    billing_sub = billing.add_subparsers(dest="billing_action", required=True)
    billing_sub.add_parser("status", help="show billing mode").set_defaults(
        func=cmd_billing_status)
    usage = billing_sub.add_parser("usage", help="summarize metered usage")
    usage.add_argument("--meter", required=True)
    usage.add_argument("--from", dest="from_", required=True)
    usage.add_argument("--to", required=True)
    usage.set_defaults(func=cmd_billing_usage)
    billing_sub.add_parser("invoices", help="list invoices").set_defaults(
        func=cmd_billing_invoices)

    registry = sub.add_parser("registry", help="registry management")
    reg_sub = registry.add_subparsers(dest="registry_action", required=True)
    reg_sub.add_parser("list", help="list visible registries").set_defaults(
        func=cmd_registry_list)
    add = reg_sub.add_parser("add", help="register a registry")
    add.add_argument("--slug", required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--type", default="PRIVATE")
    add.add_argument("--endpoint", default="")
    add.add_argument("--visibility", default="PRIVATE")
    add.add_argument("--trust", default="UNKNOWN")
    add.add_argument("--auth", default="PUBLIC")
    add.add_argument("--credential-ref", default="")
    add.set_defaults(func=cmd_registry_add)
    test = reg_sub.add_parser("test", help="test registry connection")
    test.add_argument("registry_id")
    test.set_defaults(func=cmd_registry_test)
    sync = reg_sub.add_parser("sync", help="record a registry sync")
    sync.add_argument("registry_id")
    sync.set_defaults(func=cmd_registry_sync)

    publisher = sub.add_parser("publisher", help="creator commerce")
    pub_sub = publisher.add_subparsers(dest="publisher_action", required=True)
    products = pub_sub.add_parser("products", help="list products")
    products.add_argument("--publisher", default="")
    products.set_defaults(func=cmd_publisher_products)
    revenue = pub_sub.add_parser("revenue", help="show revenue + balances")
    revenue.add_argument("--publisher", required=True)
    revenue.set_defaults(func=cmd_publisher_revenue)
    payouts = pub_sub.add_parser("payouts", help="list payouts")
    payouts.add_argument("--publisher", required=True)
    payouts.set_defaults(func=cmd_publisher_payouts)

    ent = sub.add_parser("entitlements", help="entitlement checks")
    ent_sub = ent.add_subparsers(dest="ent_action", required=True)
    check = ent_sub.add_parser("check", help="check feature access")
    check.add_argument("--feature", default="package.install")
    check.set_defaults(func=cmd_entitlements_check)

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
