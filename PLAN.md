# Aptos Auto Earn — план и статус

## Цель

Автоматизировать участие в **тестовой** сети Aptos: кран → ончейн-активность (DEX) → метрики → мониторинг аирдропов, без ручного перевода APT с другого кошелька (первый газ — только с официального крана; на testnet см. `APTOS_FAUCET_JWT` в [README](README.md)).

## Актуальная карта репозитория

| Область | Файлы |
|---------|--------|
| Конфиг | `src/config.py`, `config/config.yaml`, `.env.example` |
| Кошелёк | `src/wallet.py` |
| Кран | `src/faucet.py` (лимиты по сети в `data/faucet_state.json`, testnet JWT — см. [docs/OPS.md](docs/OPS.md)) |
| Метрики | `src/database.py` (DuckDB), в т.ч. `dex_swaps` |
| DEX | `src/activity_dex_swap.py`, проверка модулей: `python -m src.dex_diagnostics`, [docs/DEX.md](docs/DEX.md) |
| Прочие активности | `activity_lending`, `activity_nft_mint` — не on-chain по умолчанию (`ACTIVITY_ALLOW_STUBS`) |
| Аирдропы | `src/airdrop_monitor.py` (`aptos_currents`) |
| Оркестратор | `src/main.py`, вход: `run.py` |
| Тесты / CI | `tests/`, `.github/workflows/ci.yml` |
| Деплой | `deploy/aptos-auto-earn.service.example`, [docs/OPS.md](docs/OPS.md) |

## Статус продуктовых стадий

| Стадия | Содержание | Статус |
|--------|------------|--------|
| 1–2 | Инфраструктура, кошелёк, кран | Закрыты |
| 3 | Метрики, логи, ops, CI smoke | Закрыта |
| 4 | DEX Liquidswap V2 (testnet по умолчанию в YAML) | Закрыта — [docs/DEX.md](docs/DEX.md) |
| 5 | Аирдропы (Currents + задел под API) | В работе — ориентир [TODO.md](TODO.md) |
| 6 | systemd / 24×7 в проде | Запланировано |

## Маппинг «учебные имена» → репозиторий

- `wallet_manager.py` → `src/wallet.py` (`WalletManager`)
- `config.py` (корень) → `src/config.py` (`Config.load()`)
- `metrics_db.py` → `src/database.py` (`MetricsDB`)
- `main.py` (корень) → `src/main.py` + `run.py`

## Эксплуатация и дальнейшие шаги

- **Один цикл:** `python run.py --once`
- **Демон:** `python run.py` (расписание в `config.scheduler` / `SCHEDULER_*`)
- **DEX без tx:** `python -m src.dex_diagnostics --check-modules`
- **E2E (опционально):** `APTOS_E2E=1` — см. [docs/OPS.md](docs/OPS.md)

Следующий фокус: Stage 5 (ингestion аирдропов), затем Stage 6 (unit в проде по шаблону в `deploy/`).

## Риски (кратко)

- Сброс **devnet** и смена опубликованных адресов Liquidswap — сверка с [docs/DEX.md](docs/DEX.md) и веткой `devnet-addresses`.
- Кран **testnet** требует JWT Aptos Labs; **devnet** — публичный `POST /mint` без JWT.
- Парсинг аирдропов зависит от доступности внешних сайтов.

## Ресурсы

- [Aptos Docs](https://aptos.dev)
- [Faucet (ограничения testnet)](https://aptos.dev/build/apis/faucet-api)
- [Liquidswap](https://docs.liquidswap.com/smart-contracts)
- [Explorer (testnet)](https://explorer.aptoslabs.com/?network=testnet)

Подробный отчёт о состоянии: [REPORT.md](REPORT.md). Пользовательские инструкции: [README.md](README.md).
