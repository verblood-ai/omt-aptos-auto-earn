"""Aptos wallet manager."""

import json
from pathlib import Path
from typing import Dict, Any, Optional

import httpx
from loguru import logger
from aptos_sdk.account import Account
from aptos_sdk.async_client import RestClient
from aptos_sdk.bcs import Serializer
from aptos_sdk.transactions import EntryFunction, TransactionPayload
from aptos_sdk.type_tag import StructTag, TypeTag

from .config import PROJECT_ROOT


class WalletManager:
    """Manages Aptos wallet operations."""

    def __init__(self, config: "Config"):
        """Initialize wallet manager with configuration."""
        self.config = config
        self.network = config.network
        self.node_url = config.node_url
        self.client = RestClient(self.node_url)

        # Load or create wallet
        self.account = self._load_or_create_wallet()

    def _load_or_create_wallet(self) -> Account:
        """Load wallet from private key or create new one."""
        # Check for existing wallet
        wallet_file = PROJECT_ROOT / "data" / "wallet.json"
        if wallet_file.exists():
            with open(wallet_file, "r") as f:
                data = json.load(f)
                private_key_hex = data["private_key"]
                # Strip 0x prefix if present
                if private_key_hex.startswith("0x"):
                    private_key_hex = private_key_hex[2:]
                # Use load_key for hex string or from_private_key_bytes for bytes
                return Account.load_key(private_key_hex)

        # Create new wallet if private key provided via env
        private_key_hex = self.config.env.get("APTOS_PRIVATE_KEY", "").strip()
        if private_key_hex:
            if private_key_hex.startswith("0x"):
                private_key_hex = private_key_hex[2:]
            if len(private_key_hex) != 64:
                raise ValueError("Private key must be 64 hex characters (32 bytes)")
            private_key_bytes = bytes.fromhex(private_key_hex)
            account = Account.load(private_key_bytes)
        else:
            # Generate new wallet
            account = Account.generate()

        # Save wallet
        wallet_file.parent.mkdir(parents=True, exist_ok=True)
        with open(wallet_file, "w") as f:
            json.dump({
                "address": str(account.address()),
                "private_key": account.private_key.hex()
            }, f, indent=2)

        return account

    @property
    def address(self) -> str:
        """Get wallet address."""
        return str(self.account.address())

    async def get_balance(self, token_address: Optional[str] = None) -> float:
        """
        Get balance of APT or specific token.
        token_address: None for APT, or contract address for other tokens
        """
        if token_address is None:
            # Get APT balance using /balance endpoint (CoinStore deprecated after fungible_asset migration)
            # See: https://github.com/aptos-labs/aptos-developer-discussions/discussions/702
            try:
                url = f"{self.node_url}/accounts/{self.address}/balance/0x1::aptos_coin::AptosCoin"
                async with httpx.AsyncClient(trust_env=False, timeout=30.0) as client:
                    response = await client.get(url)
                    if response.status_code == 200:
                        # Response is plain text number (octas), not JSON
                        balance_octas = int(response.text.strip())
                        return balance_octas / 10**8  # 8 decimals for APT
                    elif response.status_code == 404:
                        # Account has no balance
                        return 0.0
                    else:
                        logger.error(
                            f"Balance request failed with {response.status_code}: {response.text}"
                        )
                        return 0.0
            except Exception as e:
                logger.error(f"Balance request error: {type(e).__name__}: {e}")
                return 0.0
        else:
            # Get token balance (simplified - would need token type info)
            # For now, return 0 for other tokens
            return 0.0

    async def get_account_resources(self) -> list[Dict[str, Any]]:
        """Get all account resources."""
        return await self.client.account_resources(self.address)

    async def submit_transaction(
        self,
        function: str | EntryFunction,
        type_args: list[str] = [],
        args: list[Any] = []
    ) -> str:
        """
        Submit a transaction.
        function: Either a string "address::module_name::function_name" or an EntryFunction object
        type_args: list of type arguments (used only if function is string)
        args: list of arguments (used only if function is string)
        Returns: transaction hash
        """
        entry_function = self._build_entry_function(function, type_args, args)
        payload = TransactionPayload(entry_function)

        # Use the high-level API so BCS payload/authenticator stay SDK-compatible.
        signed_transaction = await self.client.create_bcs_signed_transaction(
            self.account, payload
        )
        tx_hash = await self.client.submit_bcs_transaction(signed_transaction)
        return tx_hash

    async def simulate_transaction(
        self,
        function: str | EntryFunction,
        type_args: list[str] = [],
        args: list[Any] = []
    ) -> tuple[bool, list, str]:
        """
        Simulate a transaction without submitting it.
        Returns: (success, list_of_transactions, error_message)
        """
        entry_function = self._build_entry_function(function, type_args, args)
        payload = TransactionPayload(entry_function)

        # Create raw transaction for simulation.
        raw_transaction = await self.client.create_bcs_transaction(
            self.account, payload
        )
        # Simulate the transaction.
        result = await self.client.simulate_transaction(raw_transaction, self.account)

        if isinstance(result, (bytes, bytearray)):
            try:
                result = json.loads(result.decode("utf-8"))
            except Exception as exc:
                simulations = [
                    {
                        "success": False,
                        "vm_status": f"Failed to decode simulation response: {exc}",
                    }
                ]
                return (False, simulations, simulations[0]["vm_status"])

        if isinstance(result, list):
            simulations = result
        elif isinstance(result, dict):
            simulations = [result]
        else:
            simulations = [{"success": False, "vm_status": f"Unexpected simulation result: {result!r}"}]

        success = bool(simulations) and all(tx.get("success", False) for tx in simulations)
        error_parts = []
        if not success:
            for tx in simulations:
                if tx.get("vm_status"):
                    error_parts.append(str(tx["vm_status"]))
                elif tx.get("error"):
                    error_parts.append(str(tx["error"]))
        error_msg = "; ".join(error_parts)

        # Return tuple in expected format: (success, simulation_results, error_message)
        return (success, simulations, error_msg)

    async def wait_for_transaction(self, tx_hash: str, timeout_seconds: int = 30) -> bool:
        """Wait for transaction to be confirmed."""
        try:
            await self.client.wait_for_transaction(tx_hash, timeout_seconds=timeout_seconds)
            return True
        except Exception as e:
            logger.warning(f"Transaction wait failed: {e}")
            return False

    async def get_transaction_details(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        """Get transaction details by hash."""
        try:
            return await self.client.transaction_by_hash(tx_hash)
        except Exception:
            return None

    async def close(self):
        """Close client connection."""
        await self.client.close()

    def _build_entry_function(
        self,
        function: str | EntryFunction,
        type_args: list[str],
        args: list[Any],
    ) -> EntryFunction:
        """Normalize a function description into an Aptos entry function."""
        if isinstance(function, EntryFunction):
            return function

        parts = function.split("::")
        if len(parts) < 3:
            raise ValueError(f"Invalid function path: {function}")

        module_name = "::".join(parts[:-1])
        function_name = parts[-1]
        return EntryFunction.natural(
            module_name,
            function_name,
            [TypeTag(StructTag.from_str(t)) for t in type_args] if type_args else [],
            args,
        )
