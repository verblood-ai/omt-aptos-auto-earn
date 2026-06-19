"""Configuration loader with environment variable support."""

import os
from pathlib import Path
from typing import Dict, Any, Optional

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


class RetryPolicyConfig(BaseModel):
    attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 8.0
    jitter_ratio: float = 0.1

    @field_validator("attempts")
    @classmethod
    def validate_attempts(cls, v: int) -> int:
        if v < 1:
            raise ValueError("retry attempts must be >= 1")
        return v

    @field_validator("base_delay_seconds", "max_delay_seconds")
    @classmethod
    def validate_delays(cls, v: float) -> float:
        if v < 0:
            raise ValueError("retry delays must be >= 0")
        return v

    @field_validator("jitter_ratio")
    @classmethod
    def validate_jitter(cls, v: float) -> float:
        if v < 0 or v > 1:
            raise ValueError("retry jitter_ratio must be in [0, 1]")
        return v


class RetryConfig(BaseModel):
    rpc: RetryPolicyConfig = Field(default_factory=RetryPolicyConfig)
    faucet_http: RetryPolicyConfig = Field(
        default_factory=lambda: RetryPolicyConfig(attempts=3, base_delay_seconds=1.0, max_delay_seconds=16.0, jitter_ratio=0.1)
    )
    scraping: RetryPolicyConfig = Field(
        default_factory=lambda: RetryPolicyConfig(attempts=3, base_delay_seconds=1.0, max_delay_seconds=16.0, jitter_ratio=0.1)
    )


class ReadinessConfig(BaseModel):
    enabled: bool = True
    fail_mode: str = "closed"  # closed | open
    signal_ttl_seconds: int = 900
    mandatory_checks: list[str] = Field(
        default_factory=lambda: ["rpc_health", "min_balance_guard", "dex_preflight"]
    )
    min_balance_apt: float = 0.0
    require_dex_preflight: bool = True
    require_faucet_eligibility: bool = False
    dedup_log_window_seconds: int = 300

    @field_validator("fail_mode")
    @classmethod
    def validate_fail_mode(cls, v: str) -> str:
        val = (v or "").strip().lower()
        if val not in {"open", "closed"}:
            raise ValueError("readiness.fail_mode must be 'open' or 'closed'")
        return val

    @field_validator("signal_ttl_seconds")
    @classmethod
    def validate_signal_ttl(cls, v: int) -> int:
        if v < 30:
            raise ValueError("readiness.signal_ttl_seconds must be >= 30")
        return v

    @field_validator("min_balance_apt")
    @classmethod
    def validate_min_balance_apt(cls, v: float) -> float:
        if v < 0:
            raise ValueError("readiness.min_balance_apt must be >= 0")
        return v

    @field_validator("dedup_log_window_seconds")
    @classmethod
    def validate_dedup_window(cls, v: int) -> int:
        if v < 0:
            raise ValueError("readiness.dedup_log_window_seconds must be >= 0")
        return v

    @field_validator("mandatory_checks")
    @classmethod
    def validate_mandatory_checks(cls, values: list[str]) -> list[str]:
        allowed = {"rpc_health", "dex_preflight", "min_balance_guard", "faucet_eligibility_freshness"}
        cleaned: list[str] = []
        for raw in values:
            item = (raw or "").strip().lower()
            if not item:
                continue
            if item not in allowed:
                raise ValueError(f"Unsupported readiness check: {item}")
            if item not in cleaned:
                cleaned.append(item)
        return cleaned


class KPIAlertsConfig(BaseModel):
    enabled: bool = False
    window_hours: int = 24
    evaluation_interval_minutes: int = 30
    cooldown_minutes: int = 120
    enabled_kpis: list[str] = Field(
        default_factory=lambda: [
            "skip_rate",
            "success_rate",
            "retry_burst",
            "faucet_claim_gap",
            "airdrop_check_staleness",
        ]
    )
    skip_rate_warn: float = 0.30
    skip_rate_critical: float = 0.50
    success_rate_warn: float = 0.80
    success_rate_critical: float = 0.60
    retry_burst_warn: int = 4
    retry_burst_critical: int = 8
    faucet_claim_gap_warn_hours: int = 30
    faucet_claim_gap_critical_hours: int = 48
    airdrop_check_staleness_warn_hours: int = 12
    airdrop_check_staleness_critical_hours: int = 24

    @field_validator("window_hours", "evaluation_interval_minutes", "cooldown_minutes")
    @classmethod
    def validate_positive_window_values(cls, v: int) -> int:
        if v < 1:
            raise ValueError("kpi_alerts window/interval/cooldown values must be >= 1")
        return v

    @field_validator("retry_burst_warn", "retry_burst_critical")
    @classmethod
    def validate_retry_thresholds(cls, v: int) -> int:
        if v < 0:
            raise ValueError("kpi_alerts retry thresholds must be >= 0")
        return v

    @field_validator(
        "faucet_claim_gap_warn_hours",
        "faucet_claim_gap_critical_hours",
        "airdrop_check_staleness_warn_hours",
        "airdrop_check_staleness_critical_hours",
    )
    @classmethod
    def validate_hour_thresholds(cls, v: int) -> int:
        if v < 1:
            raise ValueError("kpi_alerts hour thresholds must be >= 1")
        return v

    @field_validator("skip_rate_warn", "skip_rate_critical", "success_rate_warn", "success_rate_critical")
    @classmethod
    def validate_ratio_thresholds(cls, v: float) -> float:
        if v < 0 or v > 1:
            raise ValueError("kpi_alerts ratio thresholds must be in [0, 1]")
        return v

    @field_validator("enabled_kpis")
    @classmethod
    def validate_enabled_kpis(cls, values: list[str]) -> list[str]:
        allowed = {"skip_rate", "success_rate", "retry_burst", "faucet_claim_gap", "airdrop_check_staleness"}
        out: list[str] = []
        for raw in values:
            item = (raw or "").strip().lower()
            if not item:
                continue
            if item not in allowed:
                raise ValueError(f"Unsupported KPI key: {item}")
            if item not in out:
                out.append(item)
        return out


class PolicyBudgetOverrideConfig(BaseModel):
    skip_budget: Optional[int] = None
    retry_budget: Optional[int] = None
    failed_runs_budget: Optional[int] = None
    execution_budget: Optional[int] = None

    @field_validator("skip_budget", "retry_budget", "failed_runs_budget", "execution_budget")
    @classmethod
    def validate_optional_budget(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("policy budgets must be >= 0")
        return v


class PolicyConfig(BaseModel):
    enabled: bool = True
    window_hours: int = 24
    skip_budget: int = 12
    retry_budget: int = 8
    failed_runs_budget: int = 6
    execution_budget: int = 200
    advisory_ratio: float = 0.85
    warning_ratios: list[float] = Field(default_factory=lambda: [0.7, 0.85, 0.95])
    module_overrides: Dict[str, PolicyBudgetOverrideConfig] = Field(default_factory=dict)

    @field_validator("window_hours")
    @classmethod
    def validate_window_hours(cls, v: int) -> int:
        if v < 1:
            raise ValueError("strategy.policy.window_hours must be >= 1")
        return v

    @field_validator("skip_budget", "retry_budget", "failed_runs_budget", "execution_budget")
    @classmethod
    def validate_budget_values(cls, v: int) -> int:
        if v < 0:
            raise ValueError("strategy policy budgets must be >= 0")
        return v

    @field_validator("advisory_ratio")
    @classmethod
    def validate_advisory_ratio(cls, v: float) -> float:
        if v < 0 or v > 1:
            raise ValueError("strategy.policy.advisory_ratio must be in [0, 1]")
        return v

    @field_validator("warning_ratios")
    @classmethod
    def validate_warning_ratios(cls, values: list[float]) -> list[float]:
        out: list[float] = []
        for value in values:
            if value < 0 or value > 1:
                raise ValueError("strategy.policy.warning_ratios values must be in [0, 1]")
            out.append(float(value))
        return out


class StrategyConfig(BaseModel):
    enabled: bool = False
    mode: str = "shadow"  # shadow | advisory | enforcement
    force_mode: str = ""  # "", shadow, advisory
    advisory_cooldown_minutes: int = 60
    policy: PolicyConfig = Field(default_factory=PolicyConfig)

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        val = (v or "").strip().lower()
        if val not in {"shadow", "advisory", "enforcement"}:
            raise ValueError("strategy.mode must be shadow, advisory or enforcement")
        return val

    @field_validator("force_mode")
    @classmethod
    def validate_force_mode(cls, v: str) -> str:
        val = (v or "").strip().lower()
        if val not in {"", "shadow", "advisory"}:
            raise ValueError("strategy.force_mode must be empty, shadow or advisory")
        return val

    @field_validator("advisory_cooldown_minutes")
    @classmethod
    def validate_advisory_cooldown(cls, v: int) -> int:
        if v < 1:
            raise ValueError("strategy.advisory_cooldown_minutes must be >= 1")
        return v


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
    readiness: ReadinessConfig = Field(default_factory=ReadinessConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    kpi_alerts: KPIAlertsConfig = Field(default_factory=KPIAlertsConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)

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

        # Readiness gate overrides
        readiness_data = dict(config_data.get("readiness") or {})
        readiness_data["enabled"] = os.getenv(
            "READINESS_ENABLED",
            str(readiness_data.get("enabled", True)),
        ).lower() == "true"
        readiness_data["fail_mode"] = os.getenv("READINESS_FAIL_MODE", readiness_data.get("fail_mode", "closed"))
        readiness_data["signal_ttl_seconds"] = int(
            os.getenv("READINESS_SIGNAL_TTL_SECONDS", readiness_data.get("signal_ttl_seconds", 900))
        )
        readiness_data["min_balance_apt"] = float(
            os.getenv("READINESS_MIN_BALANCE_APT", readiness_data.get("min_balance_apt", 0.0))
        )
        readiness_data["require_dex_preflight"] = os.getenv(
            "READINESS_REQUIRE_DEX_PREFLIGHT",
            str(readiness_data.get("require_dex_preflight", True)),
        ).lower() == "true"
        readiness_data["require_faucet_eligibility"] = os.getenv(
            "READINESS_REQUIRE_FAUCET_ELIGIBILITY",
            str(readiness_data.get("require_faucet_eligibility", False)),
        ).lower() == "true"
        readiness_data["dedup_log_window_seconds"] = int(
            os.getenv(
                "READINESS_DEDUP_LOG_WINDOW_SECONDS",
                readiness_data.get("dedup_log_window_seconds", 300),
            )
        )
        mandatory_checks_env = os.getenv("READINESS_MANDATORY_CHECKS")
        if mandatory_checks_env is not None and mandatory_checks_env.strip():
            readiness_data["mandatory_checks"] = [
                item.strip() for item in mandatory_checks_env.split(",") if item.strip()
            ]
        config_data["readiness"] = readiness_data

        # Retry policy overrides (RPC/Faucet/Scraping)
        retry_data = dict(config_data.get("retry") or {})
        rpc_retry_data = dict(retry_data.get("rpc") or {})
        rpc_retry_data["attempts"] = int(os.getenv("RETRY_RPC_ATTEMPTS", rpc_retry_data.get("attempts", 3)))
        rpc_retry_data["base_delay_seconds"] = float(
            os.getenv("RETRY_RPC_BASE_DELAY_SECONDS", rpc_retry_data.get("base_delay_seconds", 1.0))
        )
        rpc_retry_data["max_delay_seconds"] = float(
            os.getenv("RETRY_RPC_MAX_DELAY_SECONDS", rpc_retry_data.get("max_delay_seconds", 8.0))
        )
        rpc_retry_data["jitter_ratio"] = float(
            os.getenv("RETRY_RPC_JITTER_RATIO", rpc_retry_data.get("jitter_ratio", 0.1))
        )
        retry_data["rpc"] = rpc_retry_data

        faucet_retry_data = dict(retry_data.get("faucet_http") or {})
        faucet_retry_data["attempts"] = int(
            os.getenv("RETRY_FAUCET_ATTEMPTS", faucet_retry_data.get("attempts", 3))
        )
        faucet_retry_data["base_delay_seconds"] = float(
            os.getenv(
                "RETRY_FAUCET_BASE_DELAY_SECONDS",
                faucet_retry_data.get("base_delay_seconds", 1.0),
            )
        )
        faucet_retry_data["max_delay_seconds"] = float(
            os.getenv(
                "RETRY_FAUCET_MAX_DELAY_SECONDS",
                faucet_retry_data.get("max_delay_seconds", 16.0),
            )
        )
        faucet_retry_data["jitter_ratio"] = float(
            os.getenv("RETRY_FAUCET_JITTER_RATIO", faucet_retry_data.get("jitter_ratio", 0.1))
        )
        retry_data["faucet_http"] = faucet_retry_data

        scraping_retry_data = dict(retry_data.get("scraping") or {})
        scraping_retry_data["attempts"] = int(
            os.getenv("RETRY_SCRAPING_ATTEMPTS", scraping_retry_data.get("attempts", 3))
        )
        scraping_retry_data["base_delay_seconds"] = float(
            os.getenv(
                "RETRY_SCRAPING_BASE_DELAY_SECONDS",
                scraping_retry_data.get("base_delay_seconds", 1.0),
            )
        )
        scraping_retry_data["max_delay_seconds"] = float(
            os.getenv(
                "RETRY_SCRAPING_MAX_DELAY_SECONDS",
                scraping_retry_data.get("max_delay_seconds", 16.0),
            )
        )
        scraping_retry_data["jitter_ratio"] = float(
            os.getenv("RETRY_SCRAPING_JITTER_RATIO", scraping_retry_data.get("jitter_ratio", 0.1))
        )
        retry_data["scraping"] = scraping_retry_data
        config_data["retry"] = retry_data

        # KPI alerts overrides
        kpi_data = dict(config_data.get("kpi_alerts") or {})
        kpi_data["enabled"] = os.getenv("KPI_ALERTS_ENABLED", str(kpi_data.get("enabled", False))).lower() == "true"
        kpi_data["window_hours"] = int(os.getenv("KPI_ALERTS_WINDOW_HOURS", kpi_data.get("window_hours", 24)))
        kpi_data["evaluation_interval_minutes"] = int(
            os.getenv("KPI_ALERTS_EVAL_INTERVAL_MINUTES", kpi_data.get("evaluation_interval_minutes", 30))
        )
        kpi_data["cooldown_minutes"] = int(
            os.getenv("KPI_ALERTS_COOLDOWN_MINUTES", kpi_data.get("cooldown_minutes", 120))
        )
        enabled_kpis_env = os.getenv("KPI_ALERTS_ENABLED_KPIS")
        if enabled_kpis_env is not None and enabled_kpis_env.strip():
            kpi_data["enabled_kpis"] = [item.strip() for item in enabled_kpis_env.split(",") if item.strip()]
        kpi_data["skip_rate_warn"] = float(os.getenv("KPI_SKIP_RATE_WARN", kpi_data.get("skip_rate_warn", 0.30)))
        kpi_data["skip_rate_critical"] = float(
            os.getenv("KPI_SKIP_RATE_CRITICAL", kpi_data.get("skip_rate_critical", 0.50))
        )
        kpi_data["success_rate_warn"] = float(
            os.getenv("KPI_SUCCESS_RATE_WARN", kpi_data.get("success_rate_warn", 0.80))
        )
        kpi_data["success_rate_critical"] = float(
            os.getenv("KPI_SUCCESS_RATE_CRITICAL", kpi_data.get("success_rate_critical", 0.60))
        )
        kpi_data["retry_burst_warn"] = int(
            os.getenv("KPI_RETRY_BURST_WARN", kpi_data.get("retry_burst_warn", 4))
        )
        kpi_data["retry_burst_critical"] = int(
            os.getenv("KPI_RETRY_BURST_CRITICAL", kpi_data.get("retry_burst_critical", 8))
        )
        kpi_data["faucet_claim_gap_warn_hours"] = int(
            os.getenv(
                "KPI_FAUCET_CLAIM_GAP_WARN_HOURS",
                kpi_data.get("faucet_claim_gap_warn_hours", 30),
            )
        )
        kpi_data["faucet_claim_gap_critical_hours"] = int(
            os.getenv(
                "KPI_FAUCET_CLAIM_GAP_CRITICAL_HOURS",
                kpi_data.get("faucet_claim_gap_critical_hours", 48),
            )
        )
        kpi_data["airdrop_check_staleness_warn_hours"] = int(
            os.getenv(
                "KPI_AIRDROP_STALENESS_WARN_HOURS",
                kpi_data.get("airdrop_check_staleness_warn_hours", 12),
            )
        )
        kpi_data["airdrop_check_staleness_critical_hours"] = int(
            os.getenv(
                "KPI_AIRDROP_STALENESS_CRITICAL_HOURS",
                kpi_data.get("airdrop_check_staleness_critical_hours", 24),
            )
        )
        config_data["kpi_alerts"] = kpi_data

        # Strategy / policy overrides
        strategy_data = dict(config_data.get("strategy") or {})
        strategy_data["enabled"] = os.getenv(
            "STRATEGY_ENABLED",
            str(strategy_data.get("enabled", False)),
        ).lower() == "true"
        strategy_data["mode"] = os.getenv("STRATEGY_MODE", strategy_data.get("mode", "shadow"))
        strategy_data["force_mode"] = os.getenv("STRATEGY_FORCE_MODE", strategy_data.get("force_mode", ""))
        strategy_data["advisory_cooldown_minutes"] = int(
            os.getenv(
                "STRATEGY_ADVISORY_COOLDOWN_MINUTES",
                strategy_data.get("advisory_cooldown_minutes", 60),
            )
        )
        policy_data = dict(strategy_data.get("policy") or {})
        policy_data["enabled"] = os.getenv(
            "POLICY_ENABLED",
            str(policy_data.get("enabled", True)),
        ).lower() == "true"
        policy_data["window_hours"] = int(os.getenv("POLICY_WINDOW_HOURS", policy_data.get("window_hours", 24)))
        policy_data["skip_budget"] = int(os.getenv("POLICY_SKIP_BUDGET", policy_data.get("skip_budget", 12)))
        policy_data["retry_budget"] = int(os.getenv("POLICY_RETRY_BUDGET", policy_data.get("retry_budget", 8)))
        policy_data["failed_runs_budget"] = int(
            os.getenv("POLICY_FAILED_RUNS_BUDGET", policy_data.get("failed_runs_budget", 6))
        )
        policy_data["execution_budget"] = int(
            os.getenv("POLICY_EXECUTION_BUDGET", policy_data.get("execution_budget", 200))
        )
        policy_data["advisory_ratio"] = float(
            os.getenv("POLICY_ADVISORY_RATIO", policy_data.get("advisory_ratio", 0.85))
        )
        warning_ratios_env = os.getenv("POLICY_WARNING_RATIOS")
        if warning_ratios_env is not None and warning_ratios_env.strip():
            policy_data["warning_ratios"] = [
                float(item.strip()) for item in warning_ratios_env.split(",") if item.strip()
            ]
        strategy_data["policy"] = policy_data
        config_data["strategy"] = strategy_data

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
