import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.retry_policy import execute_with_retry


class _RetryableError(RuntimeError):
    pass


class _FatalError(RuntimeError):
    pass


class TestRetryPolicy(unittest.IsolatedAsyncioTestCase):
    async def test_retries_then_succeeds(self):
        call_count = {"n": 0}

        async def _operation():
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise _RetryableError("temporary")
            return "ok"

        sleep = AsyncMock()
        ok, value, err, telemetry = await execute_with_retry(
            _operation,
            attempts=3,
            base_delay_seconds=0.01,
            max_delay_seconds=0.02,
            jitter_ratio=0.0,
            is_retryable=lambda exc: isinstance(exc, _RetryableError),
            sleep_func=sleep,
        )
        self.assertTrue(ok)
        self.assertEqual(value, "ok")
        self.assertIsNone(err)
        self.assertEqual(telemetry.retries, 2)
        self.assertEqual(call_count["n"], 3)

    async def test_non_retryable_fails_fast(self):
        async def _operation():
            raise _FatalError("fatal")

        sleep = AsyncMock()
        ok, value, err, telemetry = await execute_with_retry(
            _operation,
            attempts=4,
            base_delay_seconds=0.01,
            max_delay_seconds=0.02,
            jitter_ratio=0.0,
            is_retryable=lambda exc: isinstance(exc, _RetryableError),
            sleep_func=sleep,
        )
        self.assertFalse(ok)
        self.assertIsNone(value)
        self.assertIsInstance(err, _FatalError)
        self.assertEqual(telemetry.retries, 0)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
