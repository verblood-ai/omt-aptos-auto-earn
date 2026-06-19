# TODO — Итерация 1

## Название итерации

**Execution Safety & Observability Foundation**

## Цель итерации

Собрать операционный фундамент перед внедрением policy/strategy:
- readiness gate для контролируемого запуска активностей;
- полноценные skip-метрики в DuckDB;
- KPI-алерты для раннего обнаружения деградации;
- единый backoff-подход для сетевых сбоев;
- операционный чеклист в `docs/OPS.md` для воспроизводимого прод-режима.

## Границы итерации

Включено:
- readiness-gating на уровне оркестратора и activity-модулей;
- хранение и анализ skip-событий в БД;
- алерты по KPI через существующий `TelegramNotifier` (если включен);
- унификация retry/backoff;
- ops-документация и smoke-процедуры.

Не включено:
- enforcement-решения для блокировки/ограничения стратегии (это Iteration 2);
- budgeting/policy engine в runtime (это Iteration 2);
- изменение бизнес-логики своп-стратегии beyond readiness+stability.

## Порядок выполнения и зависимости

Критический путь:
1. `I1-E1-T1` -> 2. `I1-E1-T2` -> 3. `I1-E2-T1` -> 4. `I1-E2-T2` -> 5. `I1-E4-T1` -> 6. `I1-E4-T2` -> 7. `I1-E3-T1` -> 8. `I1-E3-T2` -> 9. `I1-E3-T3` -> 10. `I1-E5-T1` -> 11. `I1-E5-T2`.

Ключевые зависимости:
- KPI-алерты (`I1-E3-*`) зависят от наличия skip-метрик (`I1-E2-*`) и стабильных retry-сигналов (`I1-E4-*`).
- OPS-чеклист (`I1-E5-*`) финализируется после фиксации runtime-поведения (`I1-E1..E4`).
- Интеграционные тесты (`I1-E1-T4`, `I1-E2-T4`, `I1-E3-T4`, `I1-E4-T4`) выполняются после соответствующих изменений кода и схемы.

---

## Эпик I1-E1: Readiness Gate

- [ ] **I1-E1-T1: Спецификация readiness-сигналов и конфигурации gate**
  - **Цель:** формализовать минимальный набор сигналов "можно/нельзя выполнять on-chain активность" и источник truth для порогов.
  - **Файлы:** `src/config.py`, `config/config.yaml`, `.env.example`, `README.md`.
  - **Критерий готовности:** конфиг включает явные gate-параметры (enable/disable, mandatory checks, TTL, fail-open/fail-closed), pydantic-валидация покрывает границы значений.
  - **Тесты/валидация:** расширить `tests/test_config.py` (валидные/невалидные значения, env overrides, дефолты).
  - **Риски:** конфликт с текущими env override-правилами; риск незаметного fail-open при ошибке загрузки конфигурации.
  - **Зависимости:** нет.
  - **Подзадачи:**
    - [ ] Описать набор сигналов readiness (RPC health, DEX preflight, min balance guard, faucet eligibility freshness).
    - [ ] Добавить структуру `readiness` в YAML и env-мэппинг в `Config.load()`.
    - [ ] Добавить pydantic-ограничения для времени жизни сигналов и режимов поведения.
    - [ ] Обновить пользовательские примеры конфигурации.

- [ ] **I1-E1-T2: Runtime gate в оркестраторе перед activity execution**
  - **Цель:** блокировать запуск модулей активности при невыполненных readiness-условиях, с детальной причиной skip.
  - **Файлы:** `src/main.py`, `src/activity_base.py`, `src/activity_dex_swap.py`.
  - **Критерий готовности:** перед `module.run()` выполняется единый gate-check, причины отказа детерминированы и логируются.
  - **Тесты/валидация:** расширить `tests/test_main_orchestrator.py`, `tests/test_main_runtime.py` сценариями gate-pass/gate-fail.
  - **Риски:** двойное гейтирование (оркестратор + модуль) может вызвать дублирование skip-сигналов.
  - **Зависимости:** `I1-E1-T1`.
  - **Подзадачи:**
    - [ ] Ввести объект результата gate-check (`ready`, `reason`, `signal_snapshot`).
    - [ ] Добавить pre-run проверку в `run_activity_cycle`.
    - [ ] Унифицировать формат skip-reason для оркестратора и модулей.
    - [ ] Добавить защиту от постоянного spam-логирования одинаковых причин.

- [ ] **I1-E1-T3: Observability для readiness состояния**
  - **Цель:** сделать состояние gate наблюдаемым для postmortem и alerting.
  - **Файлы:** `src/main.py`, `src/database.py` (через таблицу активности/новую таблицу readiness_events при необходимости), `docs/OPS.md`.
  - **Критерий готовности:** состояние gate и причины отказов доступны в логах и в DuckDB для SQL-аналитики.
  - **Тесты/валидация:** добавить проверку записи событий в `tests/test_database_writes.py` и runtime-валидацию в `tests/test_main_runtime.py`.
  - **Риски:** избыточный volume событий в БД при flap-состояниях readiness.
  - **Зависимости:** `I1-E1-T2`, `I1-E2-T1`.
  - **Подзадачи:**
    - [ ] Зафиксировать схему события readiness (timestamp, status, reason, source, metadata).
    - [ ] Реализовать запись при смене состояния gate.
    - [ ] Добавить SQL-пример "последние причины неготовности".
    - [ ] Убедиться, что metadata не содержит секретов.

- [ ] **I1-E1-T4: Тестовый контур readiness gate**
  - **Цель:** закрыть регрессионные риски при добавлении новых проверок gate.
  - **Файлы:** `tests/test_main_orchestrator.py`, `tests/test_main_runtime.py`, при необходимости новый `tests/test_readiness_gate.py`.
  - **Критерий готовности:** тесты покрывают happy-path, fail-path, stale-signal и режимы fail-open/fail-closed.
  - **Тесты/валидация:** `python -m unittest discover -s tests -v`.
  - **Риски:** brittle-тесты из-за tight coupling к текущим логам.
  - **Зависимости:** `I1-E1-T2`, `I1-E1-T3`.
  - **Подзадачи:**
    - [ ] Добавить unit-тесты на каждую gate-причину.
    - [ ] Добавить интеграционный сценарий для `run_once`.
    - [ ] Добавить negative-тест с невалидным readiness-конфигом.

---

## Эпик I1-E2: Skip-метрики в БД

- [ ] **I1-E2-T1: Расширение схемы метрик для skip-аналитики**
  - **Цель:** хранить skip как first-class событие, а не только как текст в логах.
  - **Файлы:** `src/database.py`, при необходимости `docs/OPS.md` (раздел DuckDB schema).
  - **Критерий готовности:** схема поддерживает поля `skipped`, `skip_reason`, `error_class`, `gate_reason`, `retry_count` (в существующих таблицах или новой таблице событий).
  - **Тесты/валидация:** обновить `tests/test_database_health.py`, `tests/test_database_writes.py` под новую схему.
  - **Риски:** back-compat для существующего `metrics.duckdb`; риск миграционных ошибок на старой БД.
  - **Зависимости:** нет.
  - **Подзадачи:**
    - [ ] Выбрать модель: расширение `activity_runs` vs отдельная `activity_decisions`.
    - [ ] Добавить безопасную миграцию `ALTER TABLE`/fallback при старой схеме.
    - [ ] Обновить методы вставки и typed-поля metadata.
    - [ ] Добавить smoke-проверку row_counts/DDL после миграции.

- [ ] **I1-E2-T2: Запись skip-событий в runtime-потоке**
  - **Цель:** гарантировать, что каждый skip зафиксирован в метриках с причиной и контекстом.
  - **Файлы:** `src/main.py`, `src/activity_base.py`, `src/activity_dex_swap.py`, `src/database.py`.
  - **Критерий готовности:** для всех веток skip (readiness fail, insufficient balance, simulation fail-as-skip, throttling) есть единообразная запись.
  - **Тесты/валидация:** расширить `tests/test_activity_dex_swap.py`, `tests/test_main_runtime.py`, `tests/test_database_writes.py`.
  - **Риски:** дублирование записей при нескольких уровнях обработки ошибок.
  - **Зависимости:** `I1-E2-T1`, `I1-E1-T2`.
  - **Подзадачи:**
    - [ ] Стандартизовать payload skip-события.
    - [ ] Привязать запись skip к существующему lifecycle `log_run`.
    - [ ] Добавить idempotency/guard от двойной записи в одном run.
    - [ ] Добавить regression-tests на каждую skip-ветку.

- [ ] **I1-E2-T3: KPI-ready SQL-представления для skip-данных**
  - **Цель:** дать стабильные SQL-запросы для мониторинга skip-rate без ручной дешифровки metadata.
  - **Файлы:** `docs/OPS.md`, возможно helper-методы в `src/database.py`.
  - **Критерий готовности:** есть стандартизированные запросы "skip rate by module/reason/time-window", "top skip reasons", "gate availability ratio".
  - **Тесты/валидация:** ручная валидация запросов на локальном `metrics.duckdb` после smoke-run.
  - **Риски:** дрейф схемы ломает SQL-шаблоны в OPS.
  - **Зависимости:** `I1-E2-T1`, `I1-E2-T2`.
  - **Подзадачи:**
    - [ ] Подготовить SQL-шаблоны под DuckDB JSON-функции.
    - [ ] Добавить "как читать skip reason taxonomy" в OPS.
    - [ ] Указать ожидаемые baseline-диапазоны skip-rate.

- [ ] **I1-E2-T4: Полный регресс по метрикам**
  - **Цель:** убедиться, что новая схема не ломает текущие вставки и агрегации.
  - **Файлы:** `tests/test_database_health.py`, `tests/test_database_writes.py`, `tests/test_main_runtime.py`.
  - **Критерий готовности:** все тесты метрик проходят; старые API записи (`insert_activity_run`, `record_swap`, `insert_transaction`) сохраняют совместимость.
  - **Тесты/валидация:** `python -m unittest discover -s tests -v`.
  - **Риски:** ложноположительная совместимость без тестов на legacy БД.
  - **Зависимости:** `I1-E2-T1`, `I1-E2-T2`.
  - **Подзадачи:**
    - [ ] Добавить тест инициализации на "старую" схему.
    - [ ] Добавить тест на пропуск `None` metadata без падения.
    - [ ] Проверить row_counts после mixed workload.

---

## Эпик I1-E3: KPI-алерты

- [ ] **I1-E3-T1: Определение KPI и порогов алертинга**
  - **Цель:** зафиксировать измеримые KPI readiness/стабильности и пороги тревоги.
  - **Файлы:** `src/config.py`, `config/config.yaml`, `.env.example`, `docs/OPS.md`.
  - **Критерий готовности:** конфиг поддерживает KPI threshold-параметры (ok/warn/critical), окна агрегации, cooldown для алертов.
  - **Тесты/валидация:** обновить `tests/test_config.py` для новых секций.
  - **Риски:** слишком агрессивные дефолты вызывают alert fatigue.
  - **Зависимости:** `I1-E2-T3`.
  - **Подзадачи:**
    - [ ] Формализовать KPI: skip_rate, success_rate, retry_burst, faucet_claim_gap, airdrop_check_staleness.
    - [ ] Задать значения по умолчанию и границы валидности.
    - [ ] Добавить env overrides для прод-настроек без редактирования YAML.
    - [ ] Описать матрицу severity для каждого KPI.

- [ ] **I1-E3-T2: KPI evaluator в runtime**
  - **Цель:** реализовать периодическую оценку KPI на базе DuckDB и runtime сигналов.
  - **Файлы:** `src/main.py`, `src/database.py`, возможно новый `src/kpi_alerts.py`.
  - **Критерий готовности:** по расписанию/после цикла вычисляется snapshot KPI со статусом `ok|warn|critical`.
  - **Тесты/валидация:** новые unit-тесты `tests/test_kpi_alerts.py` и расширение `tests/test_main_runtime.py`.
  - **Риски:** тяжелые SQL в основном цикле могут увеличить latency.
  - **Зависимости:** `I1-E3-T1`, `I1-E2-T2`, `I1-E4-T2`.
  - **Подзадачи:**
    - [ ] Сформировать интерфейс evaluator (input: time-window, output: violations).
    - [ ] Реализовать агрегации по таблицам activity/transactions/faucet.
    - [ ] Добавить защиту от missing data при cold start.
    - [ ] Логировать KPI snapshot в структурированном виде.

- [ ] **I1-E3-T3: Доставка алертов и защита от flood**
  - **Цель:** отправлять actionable alert-сообщения без повторного спама.
  - **Файлы:** `src/main.py`, `src/telegram_notifier.py`, возможно новый `src/kpi_alerts.py`, `data/` state-файл (gitignored) для dedup/cooldown.
  - **Критерий готовности:** алерты отправляются только при смене severity или по истечении cooldown; текст содержит KPI, текущее значение, порог, рекомендацию.
  - **Тесты/валидация:** unit-тесты с моками notifier (`tests/test_main_orchestrator.py` или `tests/test_kpi_alerts.py`).
  - **Риски:** потеря алертов при ошибке Telegram API; race-condition при повторных циклах.
  - **Зависимости:** `I1-E3-T2`.
  - **Подзадачи:**
    - [ ] Реализовать state-механику last_sent по KPI+severity.
    - [ ] Добавить fallback-логирование при недоступном Telegram.
    - [ ] Добавить шаблоны текстов для warn/critical/recovery.
    - [ ] Добавить опцию отключения отдельных KPI-алертов.

- [ ] **I1-E3-T4: Валидация KPI контуров на smoke-сценариях**
  - **Цель:** убедиться, что алерты срабатывают предсказуемо и не шумят.
  - **Файлы:** `tests/test_kpi_alerts.py` (новый), `docs/OPS.md` (раздел проверки алертов).
  - **Критерий готовности:** есть тесты на trigger/recovery/cooldown и runbook-проверка "как вручную вызвать предупреждение".
  - **Тесты/валидация:** `python -m unittest discover -s tests -v`; локальный smoke `python run.py --once` с искусственно сниженным threshold.
  - **Риски:** нестабильные тесты при завязке на текущее время.
  - **Зависимости:** `I1-E3-T3`.
  - **Подзадачи:**
    - [ ] Ввести clock abstraction для детерминированных тестов cooldown.
    - [ ] Добавить тест "recovery message после critical".
    - [ ] Описать ручной сценарий в OPS.

---

## Эпик I1-E4: Единый Backoff

- [ ] **I1-E4-T1: Общая policy retry/backoff и конфиг**
  - **Цель:** централизовать backoff-конфигурацию (attempts, base delay, max delay, jitter, retryable errors).
  - **Файлы:** `src/config.py`, `config/config.yaml`, `.env.example`, возможно новый `src/retry_policy.py`.
  - **Критерий готовности:** единая policy применяется всеми сетевыми клиентами; значения можно менять через конфиг.
  - **Тесты/валидация:** `tests/test_config.py` + unit-тесты retry policy.
  - **Риски:** изменения поведения могут повлиять на throughput и SLA цикла.
  - **Зависимости:** нет.
  - **Подзадачи:**
    - [ ] Описать retry-классы: RPC, faucet HTTP, external scraping.
    - [ ] Добавить параметры jitter и upper-bound ожидания.
    - [ ] Ввести taxonomy retryable vs non-retryable ошибок.
    - [ ] Подготовить дефолты для testnet/devnet.

- [ ] **I1-E4-T2: Интеграция backoff в faucet/dex/airdrop**
  - **Цель:** заменить локальные разрозненные ретраи на общий механизм.
  - **Файлы:** `src/activity_dex_swap.py`, `src/faucet.py`, `src/airdrop_monitor.py`, `src/wallet.py` (при необходимости).
  - **Критерий готовности:** все сетевые операции используют единый backoff API и возвращают наблюдаемые retry-метаданные.
  - **Тесты/валидация:** обновить `tests/test_activity_dex_swap.py`, `tests/test_faucet_claim.py`, `tests/test_airdrop_monitor.py`.
  - **Риски:** accidental retry неидемпотентных операций submit-транзакций.
  - **Зависимости:** `I1-E4-T1`.
  - **Подзадачи:**
    - [ ] Применить backoff к simulate/submit-safe веткам DEX.
    - [ ] Применить backoff к faucet claim HTTP.
    - [ ] Применить backoff к загрузке внешних источников airdrop.
    - [ ] Убедиться, что on-chain submit не ретраится после вероятного коммита.

- [ ] **I1-E4-T3: Retry telemetry для KPI**
  - **Цель:** сохранять retry_count/delay/error_class для последующего KPI-анализа.
  - **Файлы:** `src/database.py`, `src/main.py`, `src/activity_dex_swap.py`, `docs/OPS.md`.
  - **Критерий готовности:** retry-данные попадают в БД или structured metadata и доступны SQL-запросами.
  - **Тесты/валидация:** `tests/test_database_writes.py`, `tests/test_main_runtime.py`.
  - **Риски:** чрезмерная детализация metadata может раздувать размер БД.
  - **Зависимости:** `I1-E4-T2`, `I1-E2-T1`.
  - **Подзадачи:**
    - [ ] Добавить обязательные retry-поля в событие выполнения.
    - [ ] Встроить retry summary в транзакционные записи.
    - [ ] Подготовить SQL "retry burst за N часов".

- [ ] **I1-E4-T4: Тесты устойчивости backoff**
  - **Цель:** предотвратить регрессии retry-механизма при будущих изменениях.
  - **Файлы:** новые/обновленные тесты в `tests/test_activity_dex_swap.py`, `tests/test_faucet_claim.py`, `tests/test_airdrop_monitor.py`.
  - **Критерий готовности:** покрыты сценарии timeout, transient fail, max retries exceeded, non-retryable abort.
  - **Тесты/валидация:** `python -m unittest discover -s tests -v`.
  - **Риски:** flaky-тесты из-за реальных sleep.
  - **Зависимости:** `I1-E4-T2`.
  - **Подзадачи:**
    - [ ] Использовать mocked sleep/clock для ускорения тестов.
    - [ ] Проверить корректный рост задержки (exponential + jitter bounds).
    - [ ] Проверить отсутствие retry для non-retryable VM errors.

---

## Эпик I1-E5: OPS-чеклист и эксплуатационная готовность

- [ ] **I1-E5-T1: Расширение pre-flight и post-deploy checklist**
  - **Цель:** добавить в runbook шаги проверки readiness, skip-rate и KPI-контуров.
  - **Файлы:** `docs/OPS.md`, `README.md`.
  - **Критерий готовности:** в OPS есть разделы "Readiness gate checks", "KPI alerts smoke", "Skip-metrics SQL".
  - **Тесты/валидация:** ручной прогон чеклиста на локальной среде (`python run.py --once` + SQL smoke).
  - **Риски:** расхождение runbook и фактического поведения после следующих изменений.
  - **Зависимости:** `I1-E1-T3`, `I1-E2-T3`, `I1-E3-T4`, `I1-E4-T3`.
  - **Подзадачи:**
    - [ ] Добавить пошаговую проверку gate-предикатов перед запуском.
    - [ ] Добавить SQL-подборку для оперативной диагностики skip/retry.
    - [ ] Добавить шаблон incident-response по критическим KPI.
    - [ ] Добавить секцию "как безопасно откатить thresholds".

- [ ] **I1-E5-T2: Release checklist для закрытия Iteration 1**
  - **Цель:** формализовать единый набор приемочных шагов перед переходом к Iteration 2.
  - **Файлы:** `TODO-1.md` (эта секция), `REPORT.md` (обновление статуса после выполнения), при необходимости `PLAN.md`.
  - **Критерий готовности:** чеклист релиза закрыт, все обязательные тесты зеленые, риски и допущения задокументированы.
  - **Тесты/валидация:** полный прогон `python -m unittest discover -s tests -v`, smoke `python run.py --once`.
  - **Риски:** частичное закрытие без явной фиксации residual risk.
  - **Зависимости:** все задачи итерации.
  - **Подзадачи:**
    - [ ] Зафиксировать фактические baseline KPI после релиза.
    - [ ] Обновить статус в `REPORT.md` и связанный roadmap.
    - [ ] Подготовить handoff-заметки для Iteration 2 (strategy/policy).

---

## Definition of Done — Iteration 1

Итерация считается завершенной, если одновременно выполнены все условия:

- [ ] Реализован и протестирован readiness gate с конфигурируемым режимом поведения.
- [ ] Skip/decision-события записываются в DuckDB в структурированном виде и доступны через стандартные SQL-запросы.
- [ ] KPI evaluator рассчитывает ключевые метрики и отправляет алерты с anti-spam/cooldown логикой.
- [ ] Единый retry/backoff механизм применяется к faucet, DEX и airdrop сетевым операциям.
- [ ] `docs/OPS.md` содержит актуальный pre-flight, post-deploy smoke, incident playbook для новых механизмов.
- [ ] Unit/integration smoke (`python -m unittest discover -s tests -v`) проходит на ветке итерации.
- [ ] Риски, ограничения и open items для перехода к Iteration 2 документированы.

## Выходные артефакты итерации

- Обновленные runtime-модули (`src/main.py`, `src/database.py`, network modules).
- Обновленные конфигурации (`src/config.py`, `config/config.yaml`, `.env.example`).
- Расширенные тесты в `tests/`.
- Актуализированный runbook в `docs/OPS.md` и статус в отчетных документах.
