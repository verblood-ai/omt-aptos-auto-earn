# Aptos Auto Earn — план и статус

**Обновлено:** 2026-06-20

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
| 6 | systemd / 24×7 в проде | В работе — сервис поднят, идёт стабилизация |

## Текущий статус (оперативно)

- Основной режим запуска переведён на `systemd`: сервис `aptos-auto-earn` запущен и используется для 24×7 цикла.
- Ограничение testnet: автоклейм зависит от валидного `APTOS_FAUCET_JWT`; без JWT кран Aptos Labs недоступен.
- Ограничение исполнения активности: при низком балансе APT возможны пропуски on-chain шагов (DEX) до следующего успешного клейма.
- Приоритет смещён с «первого запуска unit» на устойчивость и предсказуемость 24×7 выполнения.

## Ближайшие итерации

### Итерация 1 — стабилизация 24×7

**Цель:** снизить долю пропусков циклов и сделать причины (`JWT`/баланс/сеть) прозрачными в логах и метриках.

**Объём:**
- Явная фиксация причин skip/fail по крану и DEX в метриках и runbook.
- Проверки перед активностью: «достаточный баланс для газа/свопа» и аккуратная деградация при нехватке средств.
- Операционные проверки `systemd`-режима (перезапуск, логи, smoke после рестарта).

**DoD:**
- После рестарта сервиса бот возвращается в рабочий цикл без ручного вмешательства.
- В DuckDB и логах различимы причины: `missing_or_expired_jwt`, `insufficient_balance`, `network_error`.
- Документация (`README.md`, `docs/OPS.md`) отражает фактический сценарий эксплуатации.

### Итерация 2 — усиление Stage 5 (airdrop ingestion)

**Цель:** повысить ценность мониторинга аирдропов и качество сигнала для оператора.

**Объём:**
- Доработка ingestion `aptos_currents`: устойчивость к временным ошибкам, дедупликация, контроль частоты запросов.
- Подготовка интерфейсов для опциональных источников (Galxe/Zealy/DappRadar) без обязательных ключей в базовом режиме.
- Улучшение итоговой отчётности за цикл (что найдено/что пропущено/почему).

**DoD:**
- Повторный прогон не создаёт дубли в `airdrops_found` для уже известных сущностей.
- При временных ошибках источника цикл завершается без падения оркестратора и с понятной записью причины.
- Stage 5 чеклист в `TODO.md` и статус в `REPORT.md` синхронизированы с фактом.

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
