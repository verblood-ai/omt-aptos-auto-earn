# Aptos Auto Earn

Автоматизированный заработок на тестовой сети Aptos.

## 🎯 Цель

Автоматически:
1. **Клеймить** 1 APT в день с крана (faucet)
2. **Выполнять активность** (DEX свопы, lending, NFT mint) для увеличения шансов на аирдропы
3. **Мониторить** новые аирдропы

## 🚀 Быстрый старт

### 1. Установка зависимостей

Перейдите в каталог проекта, создайте виртуальное окружение Python, активируйте его (на Windows путь активации отличается) и установите зависимости из `requirements.txt`.

### 2. Настройка конфигурации

Скопируйте `.env.example` в `.env` и отредактируйте: укажите приватный ключ или оставьте пустым для автогенерации кошелька; при желании задайте Telegram. Или настройте `config/config.yaml` напрямую.

Минимально для переключения сети:
- **`devnet` vs `testnet`**: задайте `APTOS_NETWORK` (см. [`.env.example`](.env.example)); при необходимости переопределите `APTOS_NODE_URL` / `FAUCET_API_URL` (в YAML или через env).

**Старт «с нуля» без перевода APT с другого кошелька:** первый газ только с **официального крана**. На **devnet** публичный `POST /mint` работает без логина. На **testnet** Aptos сейчас требует JWT с [страницы крана](https://aptos.dev/network/faucet) — вставьте токен в **`APTOS_FAUCET_JWT`** (это не пополнение чужим кошельком, а тот же бесплатный кран через сессию браузера). Лимиты крана ведутся **отдельно по сети** в `data/faucet_state.json`, поэтому клейм на devnet не блокирует testnet.

### 3. Локальный запуск (venv)

Обычный режим — **долгоживущий процесс** с внутренним расписанием: из корня репозитория, с активированным виртуальным окружением, выполните `python run.py` (или `python3 run.py`). Оркестратор будет крутить цикл планировщика, пока процесс не остановят (Ctrl+C отправляет SIGINT и корректное завершение).

Для **одного прохода** всех циклов без демона (отладка): `python run.py --once`.

**Stage 4 / DEX:** в `config/config.yaml` зафиксирована эталонная сеть **`testnet`** и адреса Liquidswap V2 (см. **[docs/DEX.md](docs/DEX.md)**). Проверка наличия модулей `scripts_v2` / `router_v2` **без отправки транзакций**: `python -m src.dex_diagnostics --check-modules`. Убедитесь, что `APTOS_NETWORK` и fullnode URL согласованы (если в `.env` указан `devnet`, а роутер — testnet-адрес, утилита покажет `no`).

### 4. Запуск как systemd-сервис (Linux)

Так удобнее держать бота на сервере: автозапуск после перезагрузки, перезапуск при падении, логи в `journalctl`. В репозитории два варианта: готовый unit под текущий путь [`deploy/aptos-auto-earn.service`](deploy/aptos-auto-earn.service) и шаблон с плейсхолдерами [`deploy/aptos-auto-earn.service.example`](deploy/aptos-auto-earn.service.example).

1. На сервере подготовьте каталог проекта, **`venv`** с зависимостями и файл **`.env`** (права `600`, не в git). В unit-файле должны совпадать **рабочий каталог** (`WorkingDirectory`) и пути к `venv/bin/python` и `run.py`.
2. Установите unit в systemd (имя сервиса `aptos-auto-earn`; **`enable` здесь не выполняется** — только установка файла и `daemon-reload`):
   - `sudo install -m 644 deploy/aptos-auto-earn.service /etc/systemd/system/aptos-auto-earn.service`
   - (на другой машине или путях отредактируйте файл перед `install` или возьмите `.example` и подставьте свои пути)
3. Отредактируйте `/etc/systemd/system/aptos-auto-earn.service`: **`User`**, **`Group`**, **`WorkingDirectory`**, **`ExecStart`**, **`EnvironmentFile`** (абсолютный путь к `.env` на машине).
4. Подхватить конфигурацию unit:
   - `sudo systemctl daemon-reload`
5. **Запуск** (когда будете готовы): `sudo systemctl start aptos-auto-earn`. Автозапуск после перезагрузки — отдельно: `sudo systemctl enable aptos-auto-earn` (по желанию; в инструкции по умолчанию **не** выполняется).
6. Проверка состояния и логов:
   - `systemctl status aptos-auto-earn`
   - `journalctl -u aptos-auto-earn -f`
7. Остановка: `sudo systemctl stop aptos-auto-earn` (процессу уходит SIGTERM; в unit задан `TimeoutStopSec` на корректное завершение).

Подробности (переменные окружения, `PYTHONUNBUFFERED`, отказ от запуска под root): **[docs/OPS.md](docs/OPS.md)**.

## 📁 Структура проекта

- **`src/`** — конфигурация, кошелёк, кран, метрики (DuckDB), активности, мониторинг аирдропов, Telegram, оркестратор.
- **`config/`** — YAML-настройки по умолчанию.
- **`data/`** — база метрик, локальные state-файлы, при автогенерации — файл кошелька (не коммитить).
- **`logs/`** — файловые логи с ротацией.
- **`tests/`** и **`.github/workflows/`** — smoke/unit-проверки и CI.
- **`run.py`** — точка входа; **`PLAN.md`**, **`REPORT.md`** — план и отчёт; **`TODO.md`** — краткий ориентир **Stage 5**.
- **`docs/OPS.md`** — эксплуатация, кран (JWT / state по сетям), метрики, CI, systemd.
- **`docs/DEX.md`** — Liquidswap: адреса, проверка модулей, devnet после reset.
- **`deploy/`** — пример unit-файла для systemd.

## 🔧 Конфигурация

### Переменные окружения (.env)

Полный список переменных и комментарии — в [`.env.example`](.env.example) (это “канонический” справочник).

| Переменная | Описание | Обязательная |
|------------|----------|--------------|
| `APTOS_NETWORK` | Сеть (`devnet` / `testnet` / `mainnet`) | Да |
| `APTOS_NODE_URL` | URL fullnode (`.../v1`) | Нет* |
| `APTOS_PRIVATE_KEY` | Приватный ключ (64 hex; можно с `0x`) | Нет** |
| `FAUCET_API_URL` | URL faucet mint endpoint | Нет* |
| `FAUCET_AMOUNT` | Сумма клейма (octas) | Нет |
| `ACTIVITY_ENABLED` | Включить активность | Нет (def: true) |
| `ACTIVITY_MODULES` | Список модулей через запятую (`dex_swap`, …) | Нет |
| `ACTIVITY_ALLOW_STUBS` | Разрешить симуляции для `lending`/`nft_mint` | Нет (def: false) |
| `DEX_SWAP_AMOUNT` | Размер свопа в octas | Нет |
| `DEX_SLIPPAGE` | Доля slippage (например `0.01`) | Нет |
| `LIQUIDSWAP_ROUTER` | Адрес пакета Liquidswap (переопределение YAML) | Нет |
| `LIQUIDSWAP_POOL_ACCOUNT` | Ресурсный аккаунт пулов (документация) | Нет |
| `LIQUIDSWAP_TEST_COINS` | Пакет тестовых монет (`::coins::USDT`) | Нет |
| `APTOS_FAUCET_JWT` | Bearer JWT для автоклейма Aptos **testnet** (см. `.env.example`; на **devnet** не нужен) | Нет |
| `AIRDROP_MONITOR_ENABLED` | Включить мониторинг | Нет (def: true) |
| `AIRDROP_APTOS_CURRENTS_URL` | URL ленты Aptos Foundation Currents | Нет |
| `TELEGRAM_BOT_TOKEN` | Токен бота Telegram | Нет |
| `TELEGRAM_CHAT_ID` | ID чата для уведомлений | Нет |

\*Если не задано, `src/config.py` подставит дефолты в зависимости от `APTOS_NETWORK` (для `devnet`/`testnet`).

\**Если не указать, будет создан новый кошелёк и сохранён в `data/wallet.json` (локально). Не коммитьте этот файл.

### YAML конфиг (config/config.yaml)

Можно настроить:
- URL ноды Aptos
- URL крана
- Параметры активности
- Настройки логирования
- Пути к базе данных

Практически важно:
- **`scheduler`**: время ежедневного крана и интервалы циклов (см. `config/config.yaml`); переопределение через `SCHEDULER_*` в `.env`.
- **`activity.modules`**: по умолчанию в репозитории включён только `dex_swap`, чтобы не запускать незавершённые модули случайно.
- **`activity.allow_stubs`**: `lending` и `nft_mint` по умолчанию **выключены** как “честные заглушки”; симуляции включаются только через `ACTIVITY_ALLOW_STUBS=true`.

## 📊 Метрики

Все данные сохраняются в DuckDB (`data/metrics.duckdb`). Таблицы: **balance_history**, **transactions** (в т.ч. поле **metadata** — JSON-текст из словаря Python, см. `docs/OPS.md`), **faucet_claims**, **airdrops_found**, **activity_runs**, **dex_swaps**. Каноническая схема и список таблиц — в `src/database.py` (константа `METRICS_TABLES`, метод `row_counts()` для smoke-проверки).

Подробности, health-check и чтение `metadata`: **[docs/OPS.md](docs/OPS.md)**.

## 🔄 Планировщик

По умолчанию (секция **`scheduler`** в `config/config.yaml`, см. также `SCHEDULER_*` в [`.env.example`](.env.example)):
- **09:00** (локальное время сервера) — клейм с крана раз в сутки
- **Каждые 6 часов** — активность и мониторинг аирдропов (интервалы задаются отдельно)
- **Каждый час** — запись баланса

Интервалы и время крана меняются **без правок кода**: YAML или переменные окружения `SCHEDULER_*`.

## 📱 Уведомления

Для включения Telegram-уведомлений:
1. Создайте бота через @BotFather
2. Укажите `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID` в `.env`
3. Установите `TELEGRAM_ENABLED=true`

Уведомления приходят:
- ✅ Успешный клейм
- ❌ Ошибка клейма
- 🛬 Найден новый аирдроп

## 🛠️ Разработка

### Запуск тестов

Та же команда, что в CI GitHub Actions:

`python -m unittest discover -s tests -v`

(на машине без симлинка `python` используйте `python3`.)

Опциональный **e2e** против выбранной сети (не в CI по умолчанию): `APTOS_E2E=1 python -m unittest tests.test_dex_e2e -v` (см. **[docs/OPS.md](docs/OPS.md)**).

## 🚑 Эксплуатация (runbook)

- **Живость сервиса:** процесс не падает сразу после старта; в логах периодически видны циклы (кран / активность / баланс). Файл БД метрик обновляется по времени после нескольких циклов.
- **Где смотреть ошибки:** консоль и `logs/aptos_auto_earn.log`; при systemd — ещё `journalctl -u <имя-сервиса> -f`.
- **Ошибки DEX / «module not published» / linker:** см. раздел в **[docs/OPS.md](docs/OPS.md)** (несовпадение адреса пакета Liquidswap с сетью после reset).
- **Откат:** остановить процесс (`systemctl stop` — SIGTERM — или Ctrl+C); при необходимости отключить модули в `config/config.yaml` или `ACTIVITY_MODULES`; сохранить копию `data/metrics.duckdb` перед экспериментами.
- **Systemd:** пошаговый запуск — в **«Быстрый старт»**, п. **4. Запуск как systemd-сервис** выше; шаблон unit — **[deploy/aptos-auto-earn.service.example](deploy/aptos-auto-earn.service.example)**; расшифровка полей — **[docs/OPS.md](docs/OPS.md)**.

### Добавление новой активности

1. Добавьте новый модуль активности в `src/` по образцу существующих.
2. Реализуйте контракт активности: проверка готовности к запуску и сам прогон с понятным результатом для оркестратора.
3. Зарегистрируйте модуль в фабрике активностей оркестратора и включите его имя в список `activity.modules` в `config/config.yaml` (или переопределите список через `ACTIVITY_MODULES` в окружении).

## ⚠️ Важные замечания

- **Тестовая сеть** — токены не имеют реальной ценности
- **Приватный ключ** — храните в безопасности, не коммитьте в git
- **Секреты и CI policy** — `.env` и runtime-файлы из `data/` не коммитятся; обязательный PR CI прогоняет только unit/smoke без real secrets (e2e запускается вручную через `APTOS_E2E=1`)
- **Куратор крана** — может меняться, следите за обновлениями
- **Активность**:
  - `dex_swap`: on-chain своп Liquidswap `scripts_v2::swap` на **testnet** по умолчанию; для **devnet** после reset сверяйте адреса ветки `devnet-addresses` и прогоняйте `python -m src.dex_diagnostics --check-modules`.
  - `lending` / `nft_mint`: пока **не on-chain**, и по умолчанию **не запускаются** (см. `ACTIVITY_ALLOW_STUBS`).

## 📈 Мониторинг

Логи пишутся в:
- Консоль (цветной вывод)
- Файл: `logs/aptos_auto_earn.log` (ротация ежедневно)

Метрики доступны через SQL-запросы к DuckDB.

## 🤝 Вклад

Это учебный/демо-проект. Pull requests приветствуются!

## 📄 Лицензия

MIT

---

**Статус (актуально на 2026-04-20):**

| Этап | Описание | Статус |
|------|----------|--------|
| 1 | Infrastructure (venv, deps, config) | ✅ COMPLETE |
| 2 | Wallet & Faucet Testing | ✅ COMPLETE |
| 3 | Metrics & Monitoring | ✅ COMPLETE (ops: [docs/OPS.md](./docs/OPS.md)) |
| 4 | Activity Implementation (Liquidswap DEX) | ✅ COMPLETE (см. `docs/DEX.md`, диагностика модулей, тесты с моками) |
| 5 | Airdrop Monitoring | 🟡 IN PROGRESS (публичный источник `aptos_currents`; Galxe/Zealy/DappRadar — только при наличии API keys); чеклист следующей стадии — **`TODO.md`** |
| 6 | Production Deployment (systemd, notifications) | ⏭️ PENDING |

**Что уже есть в коде (коротко):**
- ✅ Конфиг: `src/config.py` + `config/config.yaml` + `.env.example` (в т.ч. `APTOS_NODE_URL`, `FAUCET_API_URL`, `ACTIVITY_MODULES`, `ACTIVITY_ALLOW_STUBS`)
- ✅ Кошелёк/faucet: `src/wallet.py`, `src/faucet.py` (локальные state-файлы в `data/`, пути относительно корня репозитория)
- ✅ Метрики: `src/database.py` (включая `dex_swaps`)
- ✅ Оркестратор: `src/main.py` + `run.py`
- ✅ Минимальные тесты + CI: `tests/`, `.github/workflows/ci.yml`, `.gitignore`

**Отчёт о состоянии проекта:** [REPORT.md](./REPORT.md)

**Следующие шаги (приоритет):**
1. Stage 5: устойчивый ingestion для `aptos_currents` + (опционально) интеграции Galxe/Zealy/DappRadar по ключам (см. `TODO.md`)
2. Stage 6: systemd unit в прод-среде + политика секретов (шаблон: [deploy/aptos-auto-earn.service.example](deploy/aptos-auto-earn.service.example))
