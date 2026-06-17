"""Configuration loader with environment variable support."""

import os
from pathlib import Path
from typing import Dict, Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class FaucetConfig(BaseModel):
    max_claims_per_day: int = 1
    cooldown_hours: int = 24
    api_url: str = "https://faucet.testnet.aptoslabs.com/mint"
    # Amount to claim in octas (1 APT = 100_000_000 octas)
    amount: int = 100_000_000


class ActivityConfig(BaseModel):
    enabled: bool = True
    min_interval_minutes: int = 30
    modules: list[str] = Field(default_factory=lambda: ["dex_swap"])
    dex_swap_amount: int = 1_000_000
    dex_slippage: float = 0.01
    allow_stubs: bool = False


class AirdropConfig(BaseModel):
    enabled: bool = True
    check_interval_hours: int = 6
    sources: list[str] = Field(default_factory=lambda: ["aptos_currents"])
    aptos_currents_url: str = "https://aptosfoundation.org/currents"

    @field_validator("check_interval_hours")
    @classmethod
    def validate_check_interval_hours(cls, v: int) -> int:
        if v < 1:
            raise ValueError("airdrop.check_interval_hours must be >= 1")
        return v


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "logs/aptos_auto_earn.log"
    rotation: str = "1 day"
    retention: str = "7 days"


class MetricsConfig(BaseModel):
    db_path: str = "data/metrics.duckdb"


class SchedulerConfig(BaseModel):
    """Periodic jobs when running `run.py` as a long-lived process (see `schedule_jobs`)."""

    # Local time on the server (same format as the `schedule` library: "HH:MM").
    faucet_daily_at: str = "09:00"
    activity_interval_hours: int = 6
    airdrop_interval_hours: int = 6
    balance_interval_hours: int = 1

    @field_validator("faucet_daily_at")
    @classmethod
    def validate_faucet_time(cls, v: str) -> str:
        raw = (v or "").strip()
        parts = raw.split(":")
        if len(parts) != 2:
            raise ValueError('faucet_daily_at must look like "HH:MM" (e.g. 09:00)')
        hour_s, minute_s = parts[0].strip(), parts[1].strip()
        hour, minute = int(hour_s), int(minute_s)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("faucet_daily_at: hour must be 0-23, minute 0-59")
        return f"{hour:02d}:{minute:02d}"

    @field_validator("activity_interval_hours", "airdrop_interval_hours", "balance_interval_hours")
    @classmethod
    def validate_positive_intervals(cls, v: int) -> int:
        if v < 1:
            raise ValueError("scheduler interval hours must be >= 1")
        return v


class TelegramConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""


class ContractsConfig(BaseModel):
    # Liquidswap V2: router package (scripts_v2, router_v2, curves, …) — see docs/DEX.md
    liquidswap_router: str = "0x190d44266241744264b964a37b8f09863167a12d3e70cda39376cfb4e3561e12"
    # LP / pool resource account (documentation & future integrations)
    liquidswap_resource_account: str = "0x05a97986a9d031c4567e15b797be516910cfcb4156312482efc6a19c0a30c948"
    # Pontem test coins package (e.g. ::coins::USDT); on testnet same as historical devnet test coin addr
    liquidswap_test_coins: str = "0x43417434fd869edee76cca2a4d2301e528a1551b1d719b75c350c3c97d15b8b9"
    aave_pool: str = ""
    aave_oracle: str = ""
    nft_marketplace: str = ""


class Config(BaseModel):
    network: str = "testnet"
    node_url: str = "https://fullnode.testnet.aptoslabs.com/v1"
    faucet: FaucetConfig = Field(default_factory=FaucetConfig)
    activity: ActivityConfig = Field(default_factory=ActivityConfig)
    airdrop: AirdropConfig = Field(default_factory=AirdropConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    contracts: ContractsConfig = Field(default_factory=ContractsConfig)

    @property
    def env(self) -> Dict[str, str]:
        """Return environment variables dict for compatibility."""
        import os
        return dict(os.environ)

    @classmethod
    def load(cls, config_path: str = "config/config.yaml", env_path: str = ".env") -> "Config":
        """Load configuration from YAML file and environment variables."""
        # Load .env file if exists
        env_file = cls._resolve_path(env_path)
        if env_file.exists():
            load_dotenv(env_file, override=True)

        # Load YAML config
        config_path = cls._resolve_path(config_path)
        if config_path.exists():
            with open(config_path, "r") as f:
                config_data = yaml.safe_load(f) or {}
        else:
            config_data = {}

        # Override with environment variables
        yaml_network = str(config_data.get("network", "testnet")).strip().lower()
        network = str(os.getenv("APTOS_NETWORK", yaml_network)).strip().lower()
        config_data["network"] = network

        env_node = os.getenv("APTOS_NODE_URL")
        if env_node is not None and str(env_node).strip():
            config_data["node_url"] = str(env_node).strip()
        elif network != yaml_network:
            # APTOS_NETWORK switched relative to YAML — avoid stale fullnode URL from another network.
            config_data["node_url"] = cls._default_node_url(network)
        elif not config_data.get("node_url"):
            config_data["node_url"] = cls._default_node_url(network)

        # Faucet overrides
        faucet_data = config_data.get("faucet", {})
        faucet_data["max_claims_per_day"] = int(
            os.getenv("FAUCET_MAX_CLAIMS_PER_DAY", faucet_data.get("max_claims_per_day", 1))
        )
        faucet_data["cooldown_hours"] = int(
            os.getenv("FAUCET_COOLDOWN_HOURS", faucet_data.get("cooldown_hours", 24))
        )
        env_faucet = os.getenv("FAUCET_API_URL")
        if env_faucet is not None and str(env_faucet).strip():
            faucet_data["api_url"] = str(env_faucet).strip()
        elif network != yaml_network:
            faucet_data["api_url"] = cls._default_faucet_url(network)
        elif not faucet_data.get("api_url"):
            faucet_data["api_url"] = cls._default_faucet_url(network)
        faucet_data["amount"] = int(
            os.getenv("FAUCET_AMOUNT", faucet_data.get("amount", 100_000_000))
        )
        config_data["faucet"] = faucet_data

        # Activity overrides
        activity_data = config_data.get("activity", {})
        activity_data["enabled"] = os.getenv("ACTIVITY_ENABLED", str(activity_data.get("enabled", True))).lower() == "true"
        activity_data["min_interval_minutes"] = int(
            os.getenv("MIN_ACTIVITY_INTERVAL_MINUTES", activity_data.get("min_interval_minutes", 30))
        )
        modules_value = os.getenv("ACTIVITY_MODULES", "")
        if modules_value.strip():
            activity_data["modules"] = [module.strip() for module in modules_value.split(",") if module.strip()]
        activity_data["dex_swap_amount"] = int(
            os.getenv("DEX_SWAP_AMOUNT", activity_data.get("dex_swap_amount", 1_000_000))
        )
        activity_data["dex_slippage"] = float(
            os.getenv("DEX_SLIPPAGE", activity_data.get("dex_slippage", 0.01))
        )
        activity_data["allow_stubs"] = os.getenv(
            "ACTIVITY_ALLOW_STUBS",
            str(activity_data.get("allow_stubs", False)),
        ).lower() == "true"
        config_data["activity"] = activity_data

        scheduler_yaml = dict(config_data.get("scheduler") or {})

        # Airdrop overrides (single source of truth for airdrop interval)
        airdrop_data = config_data.get("airdrop", {})
        airdrop_data["enabled"] = os.getenv("AIRDROP_MONITOR_ENABLED", str(airdrop_data.get("enabled", True))).lower() == "true"
        env_airdrop_interval = os.getenv("AIRDROP_CHECK_INTERVAL_HOURS")
        env_scheduler_airdrop_interval = os.getenv("SCHEDULER_AIRDROP_INTERVAL_HOURS")
        if env_airdrop_interval is not None and str(env_airdrop_interval).strip():
            canonical_airdrop_interval_hours = int(env_airdrop_interval)
        elif env_scheduler_airdrop_interval is not None and str(env_scheduler_airdrop_interval).strip():
            canonical_airdrop_interval_hours = int(env_scheduler_airdrop_interval)
        elif airdrop_data.get("check_interval_hours") is not None:
            canonical_airdrop_interval_hours = int(airdrop_data.get("check_interval_hours", 6))
        else:
            canonical_airdrop_interval_hours = int(scheduler_yaml.get("airdrop_interval_hours", 6))
        airdrop_data["check_interval_hours"] = canonical_airdrop_interval_hours
        airdrop_data["aptos_currents_url"] = os.getenv(
            "AIRDROP_APTOS_CURRENTS_URL",
            airdrop_data.get("aptos_currents_url", "https://aptosfoundation.org/currents"),
        )
        config_data["airdrop"] = airdrop_data

        # Scheduler (orchestrator timing)
        scheduler_data = scheduler_yaml
        _fat = os.getenv("SCHEDULER_FAUCET_DAILY_AT")
        if _fat is not None and str(_fat).strip():
            scheduler_data["faucet_daily_at"] = str(_fat).strip()
        _act_h = os.getenv("SCHEDULER_ACTIVITY_INTERVAL_HOURS")
        if _act_h is not None and str(_act_h).strip():
            scheduler_data["activity_interval_hours"] = int(_act_h)
        scheduler_data["airdrop_interval_hours"] = canonical_airdrop_interval_hours
        _bal_h = os.getenv("SCHEDULER_BALANCE_INTERVAL_HOURS")
        if _bal_h is not None and str(_bal_h).strip():
            scheduler_data["balance_interval_hours"] = int(_bal_h)
        config_data["scheduler"] = scheduler_data

        # Logging overrides
        logging_data = config_data.get("logging", {})
        logging_data["level"] = os.getenv("LOG_LEVEL", logging_data.get("level", "INFO"))
        logging_file = os.getenv("LOG_FILE", logging_data.get("file", "logs/aptos_auto_earn.log"))
        logging_data["file"] = str(cls._resolve_path(logging_file))
        config_data["logging"] = logging_data

        # Metrics overrides
        metrics_data = config_data.get("metrics", {})
        metrics_db_path = os.getenv("METRICS_DB_PATH", metrics_data.get("db_path", "data/metrics.duckdb"))
        metrics_data["db_path"] = str(cls._resolve_path(metrics_db_path))
        config_data["metrics"] = metrics_data

        # Telegram overrides
        telegram_data = config_data.get("telegram", {})
        telegram_data["enabled"] = os.getenv("TELEGRAM_ENABLED", str(telegram_data.get("enabled", False))).lower() == "true"
        telegram_data["bot_token"] = os.getenv("TELEGRAM_BOT_TOKEN", telegram_data.get("bot_token", ""))
        telegram_data["chat_id"] = os.getenv("TELEGRAM_CHAT_ID", telegram_data.get("chat_id", ""))
        config_data["telegram"] = telegram_data

        # Contract overrides (Liquidswap)
        contracts_data = dict(config_data.get("contracts") or {})
        _lr = os.getenv("LIQUIDSWAP_ROUTER")
        if _lr is not None and str(_lr).strip():
            contracts_data["liquidswap_router"] = str(_lr).strip()
        _lp = os.getenv("LIQUIDSWAP_POOL_ACCOUNT")
        if _lp is not None and str(_lp).strip():
            contracts_data["liquidswap_resource_account"] = str(_lp).strip()
        _ltc = os.getenv("LIQUIDSWAP_TEST_COINS")
        if _ltc is not None and str(_ltc).strip():
            contracts_data["liquidswap_test_coins"] = str(_ltc).strip()
        config_data["contracts"] = contracts_data

        # Fill required defaults that may be missing from YAML (older configs)
        network = config_data.get("network", "testnet")
        if not config_data.get("node_url"):
            config_data["node_url"] = cls._default_node_url(network)

        faucet_data = config_data.get("faucet", {})
        if not faucet_data.get("api_url"):
            faucet_data["api_url"] = cls._default_faucet_url(network)
        config_data["faucet"] = faucet_data

        return cls(**config_data)

    @staticmethod
    def _resolve_path(path_value: str) -> Path:
        """Resolve project-relative paths from the repository root."""
        path = Path(path_value)
        if path.is_absolute():
            return path
        return PROJECT_ROOT / path

    @staticmethod
    def _default_node_url(network: str) -> str:
        network = (network or "testnet").lower()
        if network == "mainnet":
            return "https://fullnode.mainnet.aptoslabs.com/v1"
        if network == "devnet":
            return "https://fullnode.devnet.aptoslabs.com/v1"
        return "https://fullnode.testnet.aptoslabs.com/v1"

    @staticmethod
    def _default_faucet_url(network: str) -> str:
        network = (network or "testnet").lower()
        if network == "devnet":
            return "https://faucet.devnet.aptoslabs.com/mint"
        if network == "testnet":
            return "https://faucet.testnet.aptoslabs.com/mint"
        # mainnet has no public faucet; keep a placeholder URL that will fail fast if used
        return "https://faucet.testnet.aptoslabs.com/mint"
