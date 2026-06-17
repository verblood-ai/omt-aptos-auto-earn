"""Liquidswap / DEX diagnostics (no on-chain transactions)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any, Dict, List, Optional

import httpx

from .config import Config


def _normalize_base(node_url: str) -> str:
    return (node_url or "").rstrip("/")


def parse_module_names_from_rest_payload(payload: Any) -> List[str]:
    """Extract Move module names from GET /accounts/{addr}/modules JSON body."""
    if not isinstance(payload, list):
        return []
    names: List[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        abi = item.get("abi")
        if isinstance(abi, dict):
            n = abi.get("name")
            if isinstance(n, str) and n:
                names.append(n)
    return names


async def fetch_account_modules(client: httpx.AsyncClient, node_base: str, account: str) -> List[str]:
    """Return module names published at account (empty if none or HTTP error)."""
    url = f"{node_base}/accounts/{account}/modules"
    response = await client.get(url, timeout=30.0)
    if response.status_code != 200:
        return []
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return []
    return parse_module_names_from_rest_payload(payload)


def check_required_modules(names: List[str], required: tuple[str, ...]) -> Dict[str, bool]:
    present = set(names)
    return {m: m in present for m in required}


async def check_liquidswap_modules(
    config: Config,
    required: tuple[str, ...] = ("scripts_v2", "router_v2"),
) -> Dict[str, Any]:
    """Run a reusable Liquidswap module pre-flight check for orchestrator/CLI."""
    router = (config.contracts.liquidswap_router or "").strip()
    base = _normalize_base(config.node_url)

    if not router.startswith("0x"):
        status = {m: False for m in required}
        return {
            "ok": False,
            "network": config.network,
            "node_url": base,
            "liquidswap_router": router,
            "modules_found": 0,
            "status": status,
            "module_names": [],
            "error": "liquidswap_router is not configured",
        }

    names: List[str] = []
    error: Optional[str] = None
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            names = await fetch_account_modules(client, base, router)
    except Exception as exc:
        error = str(exc)

    status = check_required_modules(names, required)
    ok = all(status.values())
    if error:
        ok = False

    return {
        "ok": ok,
        "network": config.network,
        "node_url": base,
        "liquidswap_router": router,
        "modules_found": len(names),
        "status": status,
        "module_names": names,
        "error": error,
    }


async def run_module_check(config: Config, required: tuple[str, ...]) -> int:
    report = await check_liquidswap_modules(config=config, required=required)
    router = report["liquidswap_router"]
    base = report["node_url"]
    names = report["module_names"]
    status = report["status"]
    error = report["error"]

    print(f"network={report['network']}")
    print(f"node_url={base}")
    print(f"liquidswap_router={router}")
    if (report["network"] or "").lower() == "devnet" and router.lower().startswith("0x190d44266241744264b964a37b8f09863167a12d3e70cda39376cfb4e3561e12"):
        print(
            "warning: this router address is the official testnet/mainnet package; on devnet use the address from "
            "liquidswap devnet-addresses branch (see docs/DEX.md).",
            file=sys.stderr,
        )
    print(f"modules_found={report['modules_found']}")

    for mod, ok in status.items():
        print(f"module_{mod}={'yes' if ok else 'no'}")

    if error:
        print(f"error: {error}", file=sys.stderr)
    if names and not all(status.values()):
        print("hint: router package address may be wrong for this network (e.g. devnet reset).", file=sys.stderr)
    if not names:
        print("hint: empty module list — wrong address or unpublished package on this network.", file=sys.stderr)

    if error == "liquidswap_router is not configured":
        return 2
    return 0 if report["ok"] else 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="DEX diagnostics (no transactions).")
    parser.add_argument(
        "--check-modules",
        action="store_true",
        help="Print yes/no for scripts_v2 and router_v2 at contracts.liquidswap_router",
    )
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="Path to YAML config (default: config/config.yaml)",
    )
    args = parser.parse_args(argv)

    if not args.check_modules:
        parser.print_help()
        return 2

    config = Config.load(config_path=args.config)
    required = ("scripts_v2", "router_v2")
    return asyncio.run(run_module_check(config, required))


if __name__ == "__main__":
    raise SystemExit(main())
