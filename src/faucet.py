"""Faucet manager for Aptos testnet."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

import httpx
from loguru import logger
from aptos_sdk.account import AccountAddress
from aptos_sdk.transactions import EntryFunction, TransactionArgument, Serializer
from aptos_sdk.type_tag import TypeTag, StructTag

from .database import MetricsDB
from .config import Config, PROJECT_ROOT

# Flat `faucet_state.json` (pre–per-network) historically matched devnet-heavy setups.
_LEGACY_FLAT_NETWORK = "devnet"


class FaucetManager:
    """Manages faucet claims."""
    OCTAS_PER_APT = 100_000_000

    def __init__(self, config: Config, db: MetricsDB, wallet: "WalletManager"):
        """Initialize faucet manager."""
        self.config = config
        self.db = db
        self.wallet = wallet
        self.api_url = config.faucet.api_url
        self.max_claims_per_day = config.faucet.max_claims_per_day
        self.cooldown_hours = config.faucet.cooldown_hours
        self.amount_octas = int(config.faucet.amount)

        # State file for tracking claims
        self.state_file = PROJECT_ROOT / "data" / "faucet_state.json"
        self.state = self._load_state()

    def _is_aptos_labs_testnet_faucet(self) -> bool:
        return "faucet.testnet.aptoslabs.com" in (self.api_url or "").lower()

    def _faucet_jwt(self) -> str:
        return (os.getenv("APTOS_FAUCET_JWT") or os.getenv("FAUCET_JWT") or "").strip()

    def _load_state(self) -> Dict[str, Any]:
        """Load faucet state; support legacy flat file and per-network ``by_network``."""
        if not self.state_file.exists():
            return {"by_network": {}}

        with open(self.state_file, "r") as f:
            raw = json.load(f)

        if isinstance(raw.get("by_network"), dict):
            return raw

        # Legacy single-file format (shared across all networks — blocked zero-start on another net).
        legacy = {
            "claims_today": int(raw.get("claims_today", 0)),
            "last_claim_date": raw.get("last_claim_date"),
            "last_claim_timestamp": raw.get("last_claim_timestamp"),
        }
        logger.info(
            "Migrating flat faucet_state.json → per-network (legacy counts assigned to {} only)",
            _LEGACY_FLAT_NETWORK,
        )
        migrated = {"by_network": {_LEGACY_FLAT_NETWORK: legacy}}
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(migrated, f, indent=2)
        except OSError as exc:
            logger.warning("Could not persist migrated faucet state: {}", exc)
        return migrated

    def _save_state(self):
        """Save faucet state to file."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump(self.state, f, indent=2)

    def _network_key(self) -> str:
        return (self.config.network or "testnet").strip().lower()

    def _net_slice(self) -> Dict[str, Any]:
        """Mutable state dict for the current Aptos network."""
        by = self.state.setdefault("by_network", {})
        net = self._network_key()
        if net not in by or not isinstance(by[net], dict):
            by[net] = {"claims_today": 0, "last_claim_date": None, "last_claim_timestamp": None}
        return by[net]

    def _reset_daily_claims_if_needed(self):
        """Reset daily claims counter for this network if a new UTC day has started."""
        st = self._net_slice()
        last_date = st.get("last_claim_date")
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if last_date != today:
            st["claims_today"] = 0
            st["last_claim_date"] = today

    def can_claim(self) -> tuple[bool, str]:
        """
        Check if a claim is allowed.
        Returns: (can_claim, reason)
        """
        self._reset_daily_claims_if_needed()
        st = self._net_slice()

        # Check daily limit
        if st["claims_today"] >= self.max_claims_per_day:
            return False, f"Daily limit reached ({self.max_claims_per_day} claims/day)"

        # Check cooldown
        last_claim = st.get("last_claim_timestamp")
        if last_claim:
            last_time = datetime.fromisoformat(last_claim)
            cooldown_end = last_time + timedelta(hours=self.cooldown_hours)
            if datetime.utcnow() < cooldown_end:
                remaining = cooldown_end - datetime.utcnow()
                return False, f"Cooldown active, wait {remaining}"

        if self._is_aptos_labs_testnet_faucet() and not self._faucet_jwt():
            return (
                False,
                "Testnet: официальный кран требует JWT (см. README / .env.example: APTOS_FAUCET_JWT) "
                "или переключитесь на devnet для полностью безтокенного POST /mint",
            )

        return True, "OK"

    @property
    def amount_apt(self) -> float:
        """Faucet amount in APT for human-readable logs/notifications."""
        return self.amount_octas / self.OCTAS_PER_APT

    def format_amount(self) -> str:
        """Return faucet amount in both machine and human units."""
        return f"{self.amount_octas} octas ({self.amount_apt:.8f} APT)"

    async def claim(self) -> bool:
        """
        Claim tokens from faucet.
        Returns: True if successful, False otherwise.
        """
        can_claim, reason = self.can_claim()
        if not can_claim:
            logger.warning(f"Cannot claim: {reason}")
            return False

        try:
            async with httpx.AsyncClient(trust_env=False, timeout=30.0) as client:
                # Faucet API expects query parameters with address including 0x prefix
                # Amount should be integer (in octas: 1 APT = 100,000,000 octas)
                params = {
                    "amount": self.amount_octas,
                    "address": self.wallet.address  # Include 0x prefix
                }
                headers: Dict[str, str] = {}
                if self._is_aptos_labs_testnet_faucet():
                    jwt = self._faucet_jwt()
                    if not jwt:
                        err = "Missing APTOS_FAUCET_JWT for Aptos testnet faucet"
                        logger.error(err)
                        self.db.insert_faucet_claim(
                            network=self.config.network,
                            amount=self.amount_octas,
                            status="failed",
                            error_message=err,
                        )
                        return False
                    headers["x-is-jwt"] = "true"
                    headers["Authorization"] = jwt if jwt.lower().startswith("bearer ") else f"Bearer {jwt}"

                response = await client.post(self.api_url, params=params, headers=headers)

                if response.status_code == 200:
                    data = response.json()
                    # Faucet returns a list with tx_hash as first element: ["tx_hash"]
                    if isinstance(data, list) and len(data) > 0:
                        tx_hash = data[0]
                    else:
                        tx_hash = None

                    # Update state (per network — zero-start on a new chain is not blocked by another net)
                    st = self._net_slice()
                    st["claims_today"] = int(st.get("claims_today", 0)) + 1
                    st["last_claim_timestamp"] = datetime.utcnow().isoformat()
                    st["last_claim_date"] = datetime.utcnow().strftime("%Y-%m-%d")
                    self._save_state()

                    # Record in database
                    self.db.insert_faucet_claim(
                        network=self.config.network,
                        amount=self.amount_octas,
                        status="success",
                        tx_hash=tx_hash
                    )

                    logger.info(f"Faucet claim successful: {self.format_amount()} | TX: {tx_hash}")
                    return True
                else:
                    error_msg = f"HTTP {response.status_code}: {response.text}"
                    logger.error(f"Faucet claim failed ({self.format_amount()}): {error_msg}")

                    self.db.insert_faucet_claim(
                        network=self.config.network,
                        amount=self.amount_octas,
                        status="failed",
                        error_message=error_msg
                    )
                    return False

        except Exception as e:
            logger.error(f"Faucet claim error: {e}")
            self.db.insert_faucet_claim(
                network=self.config.network,
                amount=self.amount_octas,
                status="error",
                error_message=str(e)
            )
            return False

    async def request_pontem_faucet(
        self,
        coin_type: str,
        faucet_address: str,
        recipient_address: Optional[str] = None
    ) -> str:
        """
        Request test coins from Pontem faucet.
        
        Args:
            coin_type: Full coin type string (e.g., "0x...::coins::USDT")
            faucet_address: Faucet contract address (hex string with 0x)
            recipient_address: Optional recipient address (defaults to wallet address)
            
        Returns:
            Transaction hash
            
        Note: The recipient is the transaction sender (signer). The faucet_addr
        is passed as an argument to the request function.
        """
        if recipient_address is None:
            recipient_address = self.wallet.address
            
        # Build the entry function
        # Function: faucet::request<CoinType>
        # Type args: coin_type (as StructTag)
        # Args: faucet_addr (as address - 32-byte fixed_bytes)
        module = "0x43417434fd869edee76cca2a4d2301e528a1551b1d719b75c350c3c97d15b8b9::faucet"
        function = "request"
        
        # Parse coin type into StructTag
        type_tag = TypeTag(StructTag.from_str(coin_type))
        
        # Convert faucet address to AccountAddress object
        faucet_addr = AccountAddress.from_str(faucet_address)
        
        # Build entry function with properly serialized address argument
        entry_function = EntryFunction.natural(
            module,
            function,
            [type_tag],
            [TransactionArgument(faucet_addr, lambda ser, val: ser.fixed_bytes(val.address))]
        )
        
        # Submit transaction
        try:
            tx_hash = await self.wallet.submit_transaction(entry_function)
            logger.info(f"Pontem faucet request successful! TX: {tx_hash}")
            return tx_hash
        except Exception as e:
            logger.error(f"Pontem faucet request failed: {e}")
            raise

    def get_state(self) -> Dict[str, Any]:
        """Get current faucet state."""
        self._reset_daily_claims_if_needed()
        can_claim, reason = self.can_claim()
        st = self._net_slice()
        return {
            "network": self._network_key(),
            "can_claim": can_claim,
            "reason": reason,
            "claims_today": st["claims_today"],
            "max_claims_per_day": self.max_claims_per_day,
            "last_claim": st.get("last_claim_timestamp"),
        }
