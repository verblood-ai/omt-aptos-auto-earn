import json
import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.dex_diagnostics import (
    check_required_modules,
    fetch_account_modules,
    parse_module_names_from_rest_payload,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, json_error: Exception | None = None):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload


class _FakeClient:
    def __init__(self, response: _FakeResponse):
        self._response = response

    async def get(self, _url, timeout=30.0):
        return self._response


class TestDexDiagnostics(unittest.IsolatedAsyncioTestCase):
    def test_parse_module_names_filters_invalid_rows(self):
        payload = [
            {"abi": {"name": "scripts_v2"}},
            {"abi": {"name": "router_v2"}},
            {"abi": {"name": ""}},
            {"abi": {}},
            {"foo": "bar"},
            "bad-row",
        ]
        names = parse_module_names_from_rest_payload(payload)
        self.assertEqual(names, ["scripts_v2", "router_v2"])

    def test_check_required_modules_marks_presence(self):
        status = check_required_modules(["scripts_v2", "router_v2"], ("scripts_v2", "router_v2", "curves"))
        self.assertEqual(
            status,
            {"scripts_v2": True, "router_v2": True, "curves": False},
        )

    async def test_fetch_account_modules_returns_empty_on_non_200(self):
        client = _FakeClient(_FakeResponse(status_code=500, payload=[]))
        names = await fetch_account_modules(client, "https://node", "0x1")
        self.assertEqual(names, [])

    async def test_fetch_account_modules_returns_empty_on_invalid_json(self):
        client = _FakeClient(
            _FakeResponse(
                status_code=200,
                json_error=json.JSONDecodeError("bad json", "{}", 0),
            )
        )
        names = await fetch_account_modules(client, "https://node", "0x1")
        self.assertEqual(names, [])


if __name__ == "__main__":
    unittest.main()
