#!/usr/bin/env python3
"""OpenAgent package CLI — real, working commands for MP22 packages.

Offline commands (no server needed)::

    python scripts/openagent_package.py init my-workforce --type WORKFORCE
    python scripts/openagent_package.py validate ./my-workforce
    python scripts/openagent_package.py build ./my-workforce -o ./dist
    python scripts/openagent_package.py export ./my-workforce -o ./dist
    python scripts/openagent_package.py import ./dist/my-workforce.openagent-package.json
    python scripts/openagent_package.py inspect ./dist/my-workforce.openagent-package.json
    python scripts/openagent_package.py skill-init ./my-skill

Server commands (need OPENAGENT_API_URL + OPENAGENT_API_KEY + org)::

    python scripts/openagent_package.py publish <package-id> <version>
    python scripts/openagent_package.py install <package-id> <version>

Marketplace commands (same server env)::

    python scripts/openagent_package.py marketplace search "research"
    python scripts/openagent_package.py marketplace inspect <listing-slug>
    python scripts/openagent_package.py marketplace install <listing-id>
    python scripts/openagent_package.py publisher init --slug acme --name Acme
    python scripts/openagent_package.py publisher validate <slug>
    python scripts/openagent_package.py publisher submit <listing-id>
    python scripts/openagent_package.py publisher status <listing-id>

Secrets are never written into bundles: ``build``/``export`` abort when raw
secrets are detected.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "apps", "api", "src"))


def _manifest_from_dir(path: str) -> dict:
    manifest_path = path if path.endswith(".json") else os.path.join(path, "manifest.json")
    with open(manifest_path, encoding="utf-8") as fh:
        return json.load(fh)


def cmd_init(args: argparse.Namespace) -> int:
    from openagent.packages.builder import PackageDefinition

    pkg = (
        PackageDefinition(id=args.slug, name=args.name or args.slug,
                          version="1.0.0", type=args.type)
        .describe(args.description or "")
        .licensed("Apache-2.0")
        .changelog("1.0.0: initial draft.")
    )
    if args.author:
        pkg.authored_by(args.author)
    manifest = pkg.build()
    os.makedirs(args.directory, exist_ok=True)
    with open(os.path.join(args.directory, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"initialized package at {args.directory}/manifest.json")
    return 0


def cmd_skill_init(args: argparse.Namespace) -> int:
    from openagent.packages.builder import SkillDefinition

    skill = SkillDefinition(
        slug=args.slug, name=args.name or args.slug,
        instructions="Describe exactly what this skill does and how to verify it.",
        description=args.description or "",
    )
    os.makedirs(args.directory, exist_ok=True)
    with open(os.path.join(args.directory, "skill.json"), "w", encoding="utf-8") as fh:
        json.dump(skill.to_resource(), fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"initialized skill at {args.directory}/skill.json")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from openagent.packages import validation as validation_module

    manifest = _manifest_from_dir(args.path)
    report = validation_module.validate_package(manifest)
    print(f"passed={report['passed']} risk={report['risk']}")
    for finding in report["findings"]:
        print(f"[{finding['severity']}] {finding['code']} {finding['path']}: {finding['message']}")
    for warning in report.get("metadata_warnings", []):
        print(f"[marketplace] {warning}")
    return 0 if report["passed"] else 2


def cmd_build(args: argparse.Namespace) -> int:
    from openagent.packages import packaging as packaging_module

    manifest = _manifest_from_dir(args.path)
    files = packaging_module.build_export_files(manifest)
    os.makedirs(args.output, exist_ok=True)
    bundle_name = f"{manifest['package']['id']}-{manifest['package']['version']}.openagent-package.json"
    with open(os.path.join(args.output, bundle_name), "w", encoding="utf-8") as fh:
        json.dump({"files": files}, fh, indent=2)
        fh.write("\n")
    print(f"built {os.path.join(args.output, bundle_name)} ({len(files)} files)")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    return cmd_build(args)


def cmd_import(args: argparse.Namespace) -> int:
    from openagent.packages import packaging as packaging_module

    with open(args.bundle, encoding="utf-8") as fh:
        bundle = json.load(fh)
    files = bundle["files"] if isinstance(bundle, dict) and "files" in bundle else bundle
    preview = packaging_module.import_preview(files)
    print(json.dumps(preview, indent=2))
    return 0 if preview["valid"] else 2


def cmd_inspect(args: argparse.Namespace) -> int:
    with open(args.bundle, encoding="utf-8") as fh:
        bundle = json.load(fh)
    files = bundle["files"] if isinstance(bundle, dict) and "files" in bundle else bundle
    manifest = json.loads(files["manifest.json"])
    package = manifest["package"]
    print(f"{package['name']} ({package['id']}) v{package['version']} [{package['type']}]")
    print(f"description: {manifest.get('description', '')[:200]}")
    print(f"license: {manifest.get('license', '')}")
    print(f"dependencies: {len(manifest.get('dependencies', []))}")
    for dep in manifest.get("dependencies", []):
        print(f"  - {dep['type']}:{dep['package']} {dep.get('version', '*')}")
    print(f"resources: {len(manifest.get('resources', []))}")
    for resource in manifest.get("resources", []):
        print(f"  - {resource['kind']}:{resource['slug']} ({resource['name']})")
    return 0


def _api_request(method: str, path: str, body: dict | None = None) -> tuple[int, str]:
    import urllib.request

    base = os.environ.get("OPENAGENT_API_URL", "http://localhost:8000").rstrip("/")
    org = os.environ["OPENAGENT_ORG_ID"]
    key = os.environ["OPENAGENT_API_KEY"]
    url = f"{base}/api/v1/organizations/{org}{path}"
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


def _api_request_global(method: str, path: str, params: dict | None = None,
                        body: dict | None = None) -> tuple[int, str]:
    """API call against top-level (non-org-prefixed) marketplace routes."""
    import urllib.parse
    import urllib.request

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


def cmd_marketplace_search(args: argparse.Namespace) -> int:
    if not _require_server_env():
        return 1
    params = {"q": args.query or "", "sort": args.sort, "page": args.page,
              "page_size": args.page_size}
    if args.category:
        params["category"] = args.category
    status, body = _api_request_global("GET", "/marketplace/search", params)
    if status >= 300:
        print(f"status={status}\n{body}", file=sys.stderr)
        return 1
    payload = json.loads(body)
    for item in payload.get("data", []):
        print(f"{item.get('slug')}  v{item.get('published_version', '?')}  "
              f"[{item.get('status')}] rating={item.get('rating_average')} "
              f"({item.get('rating_count')}) installs={item.get('install_count')}  "
              f"{item.get('title')}")
    print(f"total={payload.get('meta', {}).get('total_items', '?')}")
    return 0


def cmd_marketplace_inspect(args: argparse.Namespace) -> int:
    if not _require_server_env():
        return 1
    status, body = _api_request_global("GET", f"/marketplace/{args.slug}")
    print(f"status={status}\n{body}")
    return 0 if status < 300 else 1


def cmd_marketplace_install(args: argparse.Namespace) -> int:
    if not _require_server_env():
        return 1
    values: dict = {}
    if args.values:
        with open(args.values, encoding="utf-8") as fh:
            values = json.load(fh)
    status, body = _api_request(
        "POST", f"/listings/{args.listing_id}/install",
        {"version": args.version or "", "values": values,
         "idempotency_key": args.idempotency_key or ""})
    print(f"status={status}\n{body}")
    return 0 if status < 300 else 1


def cmd_publisher_init(args: argparse.Namespace) -> int:
    if not _require_server_env():
        return 1
    status, body = _api_request_global("POST", "/publishers", {
        "display_name": args.name, "slug": args.slug,
        "publisher_type": args.type, "description": args.description or "",
        "website": args.website or ""})
    print(f"status={status}\n{body}")
    return 0 if status < 300 else 1


def cmd_publisher_validate(args: argparse.Namespace) -> int:
    if not _require_server_env():
        return 1
    status, body = _api_request_global("GET", f"/publishers/{args.slug}")
    if status >= 300:
        print(f"status={status}\n{body}", file=sys.stderr)
        return 1
    payload = json.loads(body)
    problems = []
    for field in ("display_name", "description"):
        if not payload.get(field):
            problems.append(f"missing {field}")
    if payload.get("verification_status") in ("SUSPENDED", "REVOKED"):
        problems.append(f"publisher {payload['verification_status'].lower()}")
    print(f"publisher={payload.get('slug')} verification="
          f"{payload.get('verification_status')} listings="
          f"{payload.get('published_listings')}")
    if problems:
        print("problems:")
        for problem in problems:
            print(f"  - {problem}")
        return 2
    print("publisher profile valid")
    return 0


def cmd_publisher_submit(args: argparse.Namespace) -> int:
    if not _require_server_env():
        return 1
    status, body = _api_request(
        "POST", f"/listings/{args.listing_id}/submit", {})
    print(f"status={status}\n{body}")
    return 0 if status < 300 else 1


def cmd_publisher_status(args: argparse.Namespace) -> int:
    if not _require_server_env():
        return 1
    status, body = _api_request(
        "GET", f"/listings/{args.listing_id}")
    if status >= 300:
        print(f"status={status}\n{body}", file=sys.stderr)
        return 1
    payload = json.loads(body)
    print(f"listing={payload.get('slug')} status={payload.get('status')} "
          f"version={payload.get('published_version', '?')} "
          f"rating={payload.get('rating_average')} ({payload.get('rating_count')}) "
          f"installs={payload.get('install_count')}")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    if not _require_server_env():
        return 1
    status, body = _api_request(
        "POST", f"/packages/{args.package_id}/versions/{args.version}/publish",
        {})
    print(f"status={status}\n{body}")
    return 0 if status < 300 else 1


def cmd_install(args: argparse.Namespace) -> int:
    for name in ("OPENAGENT_API_KEY", "OPENAGENT_ORG_ID"):
        if not os.environ.get(name):
            print(f"error: {name} environment variable is required", file=sys.stderr)
            return 1
    values: dict = {}
    if args.values:
        with open(args.values, encoding="utf-8") as fh:
            values = json.load(fh)
    status, body = _api_request(
        "POST", f"/packages/{args.package_id}/versions/{args.version}/install",
        {"values": values, "idempotency_key": args.idempotency_key or ""})
    print(f"status={status}\n{body}")
    return 0 if status < 300 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openagent-package",
                                     description="OpenAgent reusable package toolkit")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="scaffold a new package directory")
    init.add_argument("directory")
    init.add_argument("--slug", default="acme.example")
    init.add_argument("--name", default="")
    init.add_argument("--type", default="WORKFORCE")
    init.add_argument("--description", default="")
    init.add_argument("--author", default="")
    init.set_defaults(func=cmd_init)

    skill = sub.add_parser("skill-init", help="scaffold a new skill descriptor")
    skill.add_argument("directory")
    skill.add_argument("--slug", default="acme.skill")
    skill.add_argument("--name", default="")
    skill.add_argument("--description", default="")
    skill.set_defaults(func=cmd_skill_init)

    validate = sub.add_parser("validate", help="run the publication validation engine")
    validate.add_argument("path")
    validate.set_defaults(func=cmd_validate)

    build = sub.add_parser("build", help="build a portable bundle")
    build.add_argument("path")
    build.add_argument("-o", "--output", default="./dist")
    build.set_defaults(func=cmd_build)

    export = sub.add_parser("export", help="export a package directory to a bundle file")
    export.add_argument("path")
    export.add_argument("-o", "--output", default="./dist")
    export.set_defaults(func=cmd_export)

    imp = sub.add_parser("import", help="preview a bundle import (no writes)")
    imp.add_argument("bundle")
    imp.set_defaults(func=cmd_import)

    inspect = sub.add_parser("inspect", help="summarize a bundle file")
    inspect.add_argument("bundle")
    inspect.set_defaults(func=cmd_inspect)

    publish = sub.add_parser("publish", help="publish a version via the API")
    publish.add_argument("package_id")
    publish.add_argument("version")
    publish.set_defaults(func=cmd_publish)

    install = sub.add_parser("install", help="install a version via the API")
    install.add_argument("package_id")
    install.add_argument("version")
    install.add_argument("--values", default="")
    install.add_argument("--idempotency-key", default="")
    install.set_defaults(func=cmd_install)

    template_group = sub.add_parser("template", help="template helpers")
    template_sub = template_group.add_subparsers(dest="template_action", required=True)
    template_validate = template_sub.add_parser("validate", help="validate a template directory")
    template_validate.add_argument("path")
    template_validate.set_defaults(func=cmd_validate)

    mkt_group = sub.add_parser("marketplace", help="marketplace discovery")
    mkt_sub = mkt_group.add_subparsers(dest="marketplace_action", required=True)
    mkt_search = mkt_sub.add_parser("search", help="search marketplace listings")
    mkt_search.add_argument("query", nargs="?", default="")
    mkt_search.add_argument("--category", default="")
    mkt_search.add_argument("--sort", default="RELEVANCE")
    mkt_search.add_argument("--page", type=int, default=1)
    mkt_search.add_argument("--page-size", type=int, default=20)
    mkt_search.set_defaults(func=cmd_marketplace_search)
    mkt_inspect = mkt_sub.add_parser("inspect", help="show a listing")
    mkt_inspect.add_argument("slug")
    mkt_inspect.set_defaults(func=cmd_marketplace_inspect)
    mkt_install = mkt_sub.add_parser("install", help="install a listing")
    mkt_install.add_argument("listing_id")
    mkt_install.add_argument("--version", default="")
    mkt_install.add_argument("--values", default="")
    mkt_install.add_argument("--idempotency-key", default="")
    mkt_install.set_defaults(func=cmd_marketplace_install)

    pub_group = sub.add_parser("publisher", help="publisher workflows")
    pub_sub = pub_group.add_subparsers(dest="publisher_action", required=True)
    pub_init = pub_sub.add_parser("init", help="create a publisher profile")
    pub_init.add_argument("--slug", required=True)
    pub_init.add_argument("--name", required=True)
    pub_init.add_argument("--type", default="INDIVIDUAL")
    pub_init.add_argument("--description", default="")
    pub_init.add_argument("--website", default="")
    pub_init.set_defaults(func=cmd_publisher_init)
    pub_validate = pub_sub.add_parser("validate", help="validate a publisher profile")
    pub_validate.add_argument("slug")
    pub_validate.set_defaults(func=cmd_publisher_validate)
    pub_submit = pub_sub.add_parser("submit", help="submit a listing for review")
    pub_submit.add_argument("listing_id")
    pub_submit.set_defaults(func=cmd_publisher_submit)
    pub_status = pub_sub.add_parser("status", help="show listing status")
    pub_status.add_argument("listing_id")
    pub_status.set_defaults(func=cmd_publisher_status)

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
