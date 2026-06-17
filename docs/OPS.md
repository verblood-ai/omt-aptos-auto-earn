# Эксплуатация и метрики

Краткий ops-гайд: артефакты, pre-flight, smoke, incident playbook, backup/restore, CI и systemd.

## Где что лежит

| Артефакт | Путь (по умолчанию) | Комментарий |
|----------|---------------------|-------------|
| Логи | `logs/aptos_auto_earn.log` | Ротация в коде loguru |
| Метрики | `data/metrics.duckdb` | Не коммитить |
| Кран | `data/faucet_state.json` | Не коммитить. Формат **`by_network`**: лимиты и кулдаун **отдельно** по сетям. |
| Аирдропы | `data/airdrop_state.json` | Не коммитить |
| Кошелёк | `data/wallet.json` | Секрет; не коммитить |

Секреты хранятся только в `.env` на сервере или `EnvironmentFile` в systemd.

## Pre-flight checklist (до запуска)

Перед `python run.py` или запуском через systemd проверьте:

1. **Сеть и RPC**
   - `APTOS_NETWORK` согласован с `APTOS_NODE_URL`.
   - Fullnode отвечает на запросы (`.../v1`).
2. **Faucet**
   - `FAUCET_API_URL` соответствует сети.
   - Для Aptos testnet задан `APTOS_FAUCET_JWT`.
3. **Liquidswap**
   - `contracts.liquidswap_router` соответствует выбранной сети.
   - Прогоните `python -m src.dex_diagnostics --check-modules`; ожидается `module_scripts_v2=yes` и `module_router_v2=yes`.
4. **Права/доступ**
   - `.env`/`EnvironmentFile` имеют права `600`.
   - Пользователь сервиса имеет доступ к `data/` и `logs/`.
5. **Секреты**
   - `APTOS_PRIVATE_KEY` и `APTOS_FAUCET_JWT` не попали в git и не печатаются в логах.

## Кран (faucet)

- **Devnet:** публичный `POST` на URL из конфига, **без** JWT.
- **Testnet (Aptos Labs):** API ожидает `x-is-jwt: true` + `Authorization: Bearer ...`; используйте `APTOS_FAUCET_JWT`.
- Если JWT отсутствует, `can_claim` возвращает явную причину, без «тихих» HTTP 500.

## Сущности в DuckDB

Таблицы: `METRICS_TABLES` в `src/database.py`. Smoke: `MetricsDB.row_counts()`.

Поле **`transactions.metadata`** хранится как JSON-текст; выборки через JSON-функции DuckDB ([документация](https://duckdb.org/docs/extensions/json)).

## Health БД

1. `MetricsDB.row_counts()` выполняется без исключений.
2. В DuckDB нет ошибок чтения/записи `metrics.duckdb`.

## Признаки «живого» процесса

Периодические циклы в логах (кран / активность / баланс / аирдроп), обновление `mtime` у `metrics.duckdb`, отсутствие crash-loop на старте.

## DEX (Liquidswap)

Linker / `module not published` чаще всего означает несовпадение `APTOS_NETWORK` и `contracts.liquidswap_router` (или devnet reset). Проверка без транзакций:

```bash
python -m src.dex_diagnostics --check-modules
```

Адреса и источники: **[docs/DEX.md](DEX.md)**.

## Расписание

Источник правды для интервала аирдроп-мониторинга — `airdrop.check_interval_hours` (`AIRDROP_CHECK_INTERVAL_HOURS`).

- Оркестратор использует это значение и в scheduler-задаче airdrop.
- `SCHEDULER_AIRDROP_INTERVAL_HOURS` поддерживается как совместимый override, но приводится к тому же каноническому интервалу.
- Дополнительный guard от частого опроса: `airdrop_state.json` (`last_check`).

## Post-deploy smoke (после выкладки)

Минимальный smoke без полного e2e:

1. Выполнить один проход:
   - `python run.py --once`
2. Проверить DuckDB:
   - файл `data/metrics.duckdb` создан/обновлён;
   - `MetricsDB.row_counts()` не падает.
3. Проверить логи:
   - нет `Fatal error`;
   - есть записи по `balance`, `faucet`, `activity`, `airdrop`.
4. Для systemd:
   - `systemctl status aptos-auto-earn`
   - `journalctl -u aptos-auto-earn -n 200 --no-pager`

## Incident playbook

- **Faucet 429 / rate-limit**
  - Проверить `faucet_state.json` и параметры `FAUCET_MAX_CLAIMS_PER_DAY`, `FAUCET_COOLDOWN_HOURS`.
- **JWT missing/expired (testnet faucet)**
  - Обновить `APTOS_FAUCET_JWT` в `EnvironmentFile`, затем `daemon-reload` и restart сервиса.
- **DEX linker/module errors**
  - Сверить `APTOS_NETWORK`, `APTOS_NODE_URL`, `LIQUIDSWAP_ROUTER`, прогнать `python -m src.dex_diagnostics --check-modules`.
- **RPC/network errors**
  - Проверить доступность fullnode, DNS/egress, при необходимости временно повысить интервалы циклов.
- **Currents ingestion деградация**
  - Проверить quality-логи ingestion (`found/new/parse_errors/retries/latency`) и доступность `AIRDROP_APTOS_CURRENTS_URL`.

## Backup / restore

Бэкапить:
- `data/metrics.duckdb` (и `*.wal`, если есть),
- `data/faucet_state.json`,
- `data/airdrop_state.json`,
- `data/wallet.json` (только в защищённом хранилище).

Процедура:
1. Остановить сервис для консистентного snapshot.
2. Архивировать `data/` и хранить off-box.
3. При restore вернуть файлы и права (`chmod 600` для секретов), затем выполнить `python run.py --once`.

## Systemd

Используйте `deploy/aptos-auto-earn.service.example`.

- Запускать только от **не-root** пользователя.
- Секреты задавать только через `EnvironmentFile` вне git (`chmod 600`).
- Рекомендуемые параметры: `Restart=on-failure`, `RestartSec=30`, `NoNewPrivileges=true`, `ProtectSystem`, `ProtectHome`, `PrivateTmp`, `UMask=0077`.
- Остановка: `SIGTERM` и корректный shutdown в коде.

## CI

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

## Secrets policy и CI-практики

- Никогда не коммитить: `.env`, `APTOS_PRIVATE_KEY`, `APTOS_FAUCET_JWT`, `data/wallet.json`, runtime-state и DuckDB файлы.
- `.env.example` содержит только безопасные шаблоны.
- PR CI использует unit/smoke без real secrets.
- E2E (`APTOS_E2E=1`) остаётся ручным smoke-gate вне обязательного PR CI.

## Опциональный e2e DEX

Проверка REST модуля роутера (необязательная в CI):

```bash
export APTOS_E2E=1
python -m unittest tests.test_dex_e2e -v
```

Нужны согласованные `.env`/сеть/адреса из `config/config.yaml`.
