# TODO — Итерация 2

## Название итерации

**Policy-Driven Strategy Engine & Controlled Enforcement**

## Цель итерации

Построить управляемый слой принятия решений поверх execution-контура:
- strategy engine с этапами зрелости `shadow -> advisory -> enforcement`;
- policy thresholds и бюджеты (risk/cost/error budgets);
- детальный decision logging для аудита;
- KPI-калибровка по данным Iteration 1 для корректных policy-порогов.

## Входные условия (Entry Criteria)

Перед стартом итерации ожидается:
- закрыт DoD Iteration 1;
- readiness gate/skip-метрики/KPI-алерты работают стабильно;
- собран baseline минимум за несколько runtime-циклов (желательно 3-7 дней).

## Границы итерации

Включено:
- движок стратегий и выбор режима исполнения;
- policy-конфиг и runtime budget checks;
- сохранение решений и обоснований в DuckDB;
- методика и реализация KPI calibration;
- rollout-гайд для безопасного перехода в enforcement.

Не включено:
- добавление новых продуктовых активностей (новых модулей beyond existing set);
- внешние дашборды/BI-пайплайны (вне DuckDB + docs);
- сложные ML/оптимизационные алгоритмы (rule-based engine достаточно).

## Порядок выполнения и зависимости

Критический путь:
1. `I2-E1-T1` -> 2. `I2-E1-T2` -> 3. `I2-E2-T1` -> 4. `I2-E2-T2` -> 5. `I2-E3-T1` -> 6. `I2-E1-T3` -> 7. `I2-E1-T4` -> 8. `I2-E4-T1` -> 9. `I2-E4-T2` -> 10. `I2-E4-T3` -> 11. `I2-E5-T1`.

Ключевые зависимости:
- enforcement (`I2-E1-T4`) запрещен до завершения decision logging (`I2-E3-*`) и калибровки KPI (`I2-E4-*`).
- budgets (`I2-E2-*`) зависят от наблюдаемости skip/retry/KPI из Iteration 1.
- OPS rollout (`I2-E5-*`) финализируется только после тестового прогона всех трех режимов.

---

## Эпик I2-E1: Strategy Engine (shadow -> advisory -> enforcement)

- [ ] **I2-E1-T1: Спецификация engine-состояний и переходов**
  - **Цель:** формализовать state machine режимов `shadow`, `advisory`, `enforcement` и условия переходов.
  - **Файлы:** `PLAN.md`, `README.md`, `src/config.py`, `config/config.yaml`, `.env.example`.
  - **Критерий готовности:** задокументированы режимы, правила переключения, аварийный fallback в более безопасный режим.
  - **Тесты/валидация:** обновить `tests/test_config.py` для новых полей режима.
  - **Риски:** неоднозначные правила перехода приведут к непредсказуемому runtime-поведению.
  - **Зависимости:** выполненный DoD Iteration 1.
  - **Подзадачи:**
    - [ ] Ввести enum/строгую типизацию режима стратегии.
    - [ ] Описать policy gate для перехода `shadow -> advisory` и `advisory -> enforcement`.
    - [ ] Добавить rollback-правило при critical KPI деградации.
    - [ ] Обновить пользовательскую документацию по режимам.

- [ ] **I2-E1-T2: Каркас strategy engine и интеграция в orchestration loop**
  - **Цель:** внедрить единый decision-point перед запуском активности.
  - **Файлы:** `src/main.py`, возможно новые `src/strategy_engine.py`, `src/policy_engine.py`.
  - **Критерий готовности:** перед `module.run()` создается Decision объект с action: `allow`, `warn`, `block`, `defer`.
  - **Тесты/валидация:** новые тесты `tests/test_strategy_engine.py`, расширение `tests/test_main_runtime.py`.
  - **Риски:** дублирование логики между readiness gate и strategy engine.
  - **Зависимости:** `I2-E1-T1`.
  - **Подзадачи:**
    - [ ] Ввести интерфейс engine (`evaluate(context) -> decision`).
    - [ ] Пробросить execution context (KPI snapshot, budgets, module state).
    - [ ] Сохранить совместимость со старым поведением при `mode=shadow`.
    - [ ] Добавить trace-id/correlation-id для цепочки решений.

- [ ] **I2-E1-T3: Реализация режима advisory**
  - **Цель:** в advisory режиме формировать рекомендации, не блокируя фактическое выполнение.
  - **Файлы:** `src/main.py`, `src/strategy_engine.py`, `src/telegram_notifier.py`, `docs/OPS.md`.
  - **Критерий готовности:** advisory-решения записываются и могут отправляться как warning, но выполнение сохраняется.
  - **Тесты/валидация:** `tests/test_strategy_engine.py`, `tests/test_main_orchestrator.py`.
  - **Риски:** advisory spam при частых одинаковых рекомендациях.
  - **Зависимости:** `I2-E1-T2`, `I2-E3-T1`.
  - **Подзадачи:**
    - [ ] Добавить decision type `advisory_notice` и reason taxonomy.
    - [ ] Реализовать dedup/cooldown для advisory-уведомлений.
    - [ ] Добавить явный маркер "executed_despite_advisory".
    - [ ] Обновить runbook диагностики advisory-рекомендаций.

- [ ] **I2-E1-T4: Реализация режима enforcement**
  - **Цель:** разрешать/блокировать действия на основании policy-решений.
  - **Файлы:** `src/main.py`, `src/strategy_engine.py`, `src/policy_engine.py`, `docs/OPS.md`.
  - **Критерий готовности:** в enforcement блокирующие решения реально предотвращают запуск операции и фиксируются как policy-denied skip.
  - **Тесты/валидация:** `tests/test_strategy_engine.py`, `tests/test_main_runtime.py`, `tests/test_main_orchestrator.py`.
  - **Риски:** false positive блокировки могут остановить полезную активность.
  - **Зависимости:** `I2-E1-T3`, `I2-E2-T2`, `I2-E3-T2`, `I2-E4-T2`.
  - **Подзадачи:**
    - [ ] Реализовать action `block` с обязательным reason и remediation hint.
    - [ ] Ввести emergency override (`force_shadow`/`force_advisory`).
    - [ ] Добавить защиту от "permanent block" без auto-recheck.
    - [ ] Описать процедуру безопасного включения enforcement.

- [ ] **I2-E1-T5: End-to-end тестирование жизненного цикла режимов**
  - **Цель:** проверить корректность поведения при смене режимов и rollback.
  - **Файлы:** `tests/test_strategy_engine.py`, возможно новый `tests/test_strategy_modes_e2e.py`.
  - **Критерий готовности:** тесты покрывают последовательность `shadow -> advisory -> enforcement -> fallback`.
  - **Тесты/валидация:** `python -m unittest discover -s tests -v`.
  - **Риски:** тесты могут быть хрупкими без контролируемого clock/state.
  - **Зависимости:** `I2-E1-T4`.
  - **Подзадачи:**
    - [ ] Добавить deterministic fixtures контекста.
    - [ ] Проверить отсутствие side-effect в shadow.
    - [ ] Проверить обязательный decision log в каждом режиме.

---

## Эпик I2-E2: Policy thresholds и budgets

- [ ] **I2-E2-T1: Модель policy-порогов и budget-контуров**
  - **Цель:** определить управляемые ограничения: skip budget, retry budget, failed tx budget, execution budget.
  - **Файлы:** `src/config.py`, `config/config.yaml`, `.env.example`, `docs/OPS.md`.
  - **Критерий готовности:** конфиг выражает policy по окнам времени (hour/day), scope (global/module), severity и action.
  - **Тесты/валидация:** `tests/test_config.py`.
  - **Риски:** слишком сложная конфигурация затруднит эксплуатацию.
  - **Зависимости:** `I2-E1-T1`, KPI baseline из Iteration 1.
  - **Подзадачи:**
    - [ ] Описать структуру policy-rule (condition, threshold, window, action).
    - [ ] Добавить budget-поля и валидации диапазонов.
    - [ ] Добавить глобальные и модульные overrides.
    - [ ] Добавить sane defaults для безопасного старта.

- [ ] **I2-E2-T2: Runtime policy evaluator**
  - **Цель:** вычислять бюджетные нарушения и policy outcomes в реальном времени.
  - **Файлы:** `src/policy_engine.py` (новый), `src/database.py`, `src/main.py`.
  - **Критерий готовности:** evaluator возвращает перечень сработавших правил и итоговое действие.
  - **Тесты/валидация:** `tests/test_policy_engine.py` (новый), `tests/test_main_runtime.py`.
  - **Риски:** высокая стоимость агрегаций по большим временным окнам.
  - **Зависимости:** `I2-E2-T1`, `I2-E3-T1`.
  - **Подзадачи:**
    - [ ] Реализовать загрузку policy из Config.
    - [ ] Добавить агрегации по skip/retry/failure KPI.
    - [ ] Реализовать приоритизацию правил при конфликте action.
    - [ ] Добавить fallback на безопасное действие при ошибке evaluator.

- [ ] **I2-E2-T3: Budget burn-rate и early warning**
  - **Цель:** отслеживать скорость расходования budgets до hard limit.
  - **Файлы:** `src/policy_engine.py`, `src/main.py`, `src/telegram_notifier.py`, `docs/OPS.md`.
  - **Критерий готовности:** есть предупреждения о приближении к лимиту (например 70/85/95%), до наступления `block`.
  - **Тесты/валидация:** `tests/test_policy_engine.py`, `tests/test_kpi_alerts.py` (расширение).
  - **Риски:** слишком частые предупреждения при шумном ряде.
  - **Зависимости:** `I2-E2-T2`, `I2-E4-T2`.
  - **Подзадачи:**
    - [ ] Добавить расчет burn-rate по окну времени.
    - [ ] Ввести threshold ladder для предупреждений.
    - [ ] Добавить anti-spam на уровне budget alerts.

- [ ] **I2-E2-T4: Валидация policy-бюджетов на synthetic сценариях**
  - **Цель:** проверить корректность блокировок и предупреждений в контрольных нагрузках.
  - **Файлы:** `tests/test_policy_engine.py`, возможно новый `tests/test_policy_budgets_scenarios.py`.
  - **Критерий готовности:** сценарии "budget exhausted", "near exhaustion", "recovery window" дают ожидаемые decisions.
  - **Тесты/валидация:** `python -m unittest discover -s tests -v`.
  - **Риски:** высокая сложность synthetic dataset fixtures.
  - **Зависимости:** `I2-E2-T3`.
  - **Подзадачи:**
    - [ ] Подготовить фикстуры с разными профилями skip/failure.
    - [ ] Проверить recovery после истечения окна.
    - [ ] Проверить приоритет критических правил над advisory.

---

## Эпик I2-E3: Decision Logging (auditability)

- [ ] **I2-E3-T1: Схема decision log и API записи**
  - **Цель:** сделать каждое стратегическое решение аудируемым.
  - **Файлы:** `src/database.py`, возможно новый `src/decision_log.py`.
  - **Критерий готовности:** в БД есть структурированная запись: режим, decision action, rule hits, inputs, outcome, correlation id.
  - **Тесты/валидация:** `tests/test_database_writes.py`, `tests/test_database_health.py`.
  - **Риски:** рост объема таблицы decision log и влияние на I/O.
  - **Зависимости:** `I2-E1-T2`.
  - **Подзадачи:**
    - [ ] Спроектировать таблицу `strategy_decisions` (или эквивалент).
    - [ ] Добавить insert API и сериализацию metadata в JSON.
    - [ ] Добавить retention/архивную стратегию для большого объема.
    - [ ] Добавить индексы/ключи для частых выборок.

- [ ] **I2-E3-T2: Интеграция decision log в runtime execution path**
  - **Цель:** логировать decision до и после фактического выполнения модуля.
  - **Файлы:** `src/main.py`, `src/strategy_engine.py`, `src/database.py`.
  - **Критерий готовности:** есть связка "decision -> execution result", позволяющая анализировать качество решений.
  - **Тесты/валидация:** `tests/test_main_runtime.py`, `tests/test_strategy_engine.py`.
  - **Риски:** неполные логи при исключениях между decision и execution.
  - **Зависимости:** `I2-E3-T1`, `I2-E1-T3`.
  - **Подзадачи:**
    - [ ] Добавить correlation-id на весь lifecycle шага.
    - [ ] Писать final outcome (`executed`, `blocked`, `failed`, `skipped`).
    - [ ] Обеспечить запись even-on-exception через `finally`.

- [ ] **I2-E3-T3: SQL-аналитика качества решений**
  - **Цель:** обеспечить базовую explainability: насколько решения были полезны или избыточны.
  - **Файлы:** `docs/OPS.md`, возможно helper в `src/database.py`.
  - **Критерий готовности:** есть SQL-шаблоны для анализа precision-like метрик policy (сколько блокировок предотвращали failure, сколько advisory игнорировались без последствий).
  - **Тесты/валидация:** ручная проверка SQL на тестовом `metrics.duckdb`.
  - **Риски:** интерпретация причинности может быть ограниченной без дополнительных сигналов.
  - **Зависимости:** `I2-E3-T2`, `I2-E4-T2`.
  - **Подзадачи:**
    - [ ] Добавить набор запросов decision outcome matrix.
    - [ ] Добавить примеры weekly review по policy.
    - [ ] Добавить guidance по tuning threshold на основе decision logs.

- [ ] **I2-E3-T4: Тесты целостности decision logging**
  - **Цель:** гарантировать, что decision log не теряется и не рассинхронизируется с исполнением.
  - **Файлы:** `tests/test_strategy_engine.py`, `tests/test_database_writes.py`, новый `tests/test_decision_logging.py`.
  - **Критерий готовности:** тестами проверены уникальность correlation-id, обязательные поля, консистентность decision/outcome.
  - **Тесты/валидация:** `python -m unittest discover -s tests -v`.
  - **Риски:** ложные падения тестов из-за nondeterministic timestamps.
  - **Зависимости:** `I2-E3-T2`.
  - **Подзадачи:**
    - [ ] Ввести test helper для normalized timestamp comparison.
    - [ ] Проверить запись в ситуациях exception path.
    - [ ] Проверить совместимость со старой схемой БД.

---

## Эпик I2-E4: KPI-калибровка

- [ ] **I2-E4-T1: Сбор baseline и профиль распределений KPI**
  - **Цель:** получить эмпирические диапазоны KPI для корректной установки policy thresholds.
  - **Файлы:** `docs/OPS.md`, `REPORT.md`, возможно `src/database.py` (helper queries).
  - **Критерий готовности:** зафиксированы P50/P90/P95 по ключевым KPI (skip_rate, retry_rate, fail_rate, cycle_latency).
  - **Тесты/валидация:** ручной SQL-аудит baseline на данных Iteration 1.
  - **Риски:** недостаточный объем данных для статистически устойчивых порогов.
  - **Зависимости:** завершенная эксплуатация Iteration 1.
  - **Подзадачи:**
    - [ ] Определить минимальное окно наблюдения.
    - [ ] Подготовить SQL-запросы для percentile/аномалий.
    - [ ] Зафиксировать baseline в `REPORT.md`.

- [ ] **I2-E4-T2: Настройка threshold/budget значений по baseline**
  - **Цель:** перевести эмпирические KPI в рабочие policy-пороги и бюджеты.
  - **Файлы:** `config/config.yaml`, `.env.example`, `src/config.py`, `docs/OPS.md`.
  - **Критерий готовности:** значения threshold и budget обоснованы baseline и задокументированы.
  - **Тесты/валидация:** `tests/test_config.py`, synthetic проверки в `tests/test_policy_engine.py`.
  - **Риски:** дрейф поведения сети (testnet/devnet) сделает пороги быстро устаревшими.
  - **Зависимости:** `I2-E4-T1`, `I2-E2-T1`.
  - **Подзадачи:**
    - [ ] Выбрать initial threshold ladder для warn/critical/block.
    - [ ] Настроить отдельные пороги для разных module_name при необходимости.
    - [ ] Описать процедуру periodic recalibration.

- [ ] **I2-E4-T3: Dry-run калибровки в shadow/advisory режимах**
  - **Цель:** проверить, как policy сработала бы на реальном потоке без риска блокировки.
  - **Файлы:** `src/strategy_engine.py`, `src/policy_engine.py`, `docs/OPS.md`.
  - **Критерий готовности:** подготовлен отчет "что было бы заблокировано" в shadow/advisory и подтверждена приемлемая частота блокировок перед enforcement.
  - **Тесты/валидация:** runtime smoke + анализ decision log за тестовый период.
  - **Риски:** несоответствие dry-run и прод-поведения при редких событиях.
  - **Зависимости:** `I2-E1-T3`, `I2-E3-T3`, `I2-E4-T2`.
  - **Подзадачи:**
    - [ ] Добавить агрегированный отчет по hypothetical blocks.
    - [ ] Зафиксировать критерии go/no-go для enforcement.
    - [ ] Подготовить список ручных корректировок thresholds.

- [ ] **I2-E4-T4: Автотесты калибровки и регресс threshold logic**
  - **Цель:** предотвратить дрейф policy-логики при будущих изменениях.
  - **Файлы:** `tests/test_policy_engine.py`, `tests/test_strategy_engine.py`.
  - **Критерий готовности:** тесты покрывают пересечение thresholds, hysteresis и recovery-переходы.
  - **Тесты/валидация:** `python -m unittest discover -s tests -v`.
  - **Риски:** сложность поддержки большого числа сценариев.
  - **Зависимости:** `I2-E4-T2`, `I2-E4-T3`.
  - **Подзадачи:**
    - [ ] Добавить тесты hysteresis (не дергаться на границе порога).
    - [ ] Добавить тесты priority resolution при множественных нарушениях.
    - [ ] Добавить тесты на recovery и auto-downgrade severity.

---

## Эпик I2-E5: Rollout, governance, и handoff

- [ ] **I2-E5-T1: Rollout план включения enforcement**
  - **Цель:** безопасно перевести систему в policy-enforced execution.
  - **Файлы:** `docs/OPS.md`, `README.md`, `PLAN.md`.
  - **Критерий готовности:** есть пошаговый rollout: shadow soak -> advisory soak -> enforcement canary -> full enforcement.
  - **Тесты/валидация:** ручной dry-run по чеклисту + подтверждение KPI stability.
  - **Риски:** premature enforcement на нестабильной сети.
  - **Зависимости:** `I2-E1-T5`, `I2-E2-T4`, `I2-E4-T3`.
  - **Подзадачи:**
    - [ ] Описать минимальную длительность каждого soak-периода.
    - [ ] Описать rollback-триггеры и rollback-команды/настройки.
    - [ ] Добавить контрольный список для ночного и дневного окна релиза.

- [ ] **I2-E5-T2: Governance и регулярный policy review**
  - **Цель:** закрепить процесс сопровождения policy-порогов и бюджетов.
  - **Файлы:** `docs/OPS.md`, `REPORT.md`.
  - **Критерий готовности:** описан ритм ревью (например weekly), ответственные артефакты и метрики для пересмотра.
  - **Тесты/валидация:** process validation по шаблону еженедельного отчета.
  - **Риски:** отсутствие регулярного тюнинга приведет к деградации качества решений.
  - **Зависимости:** `I2-E3-T3`, `I2-E4-T3`.
  - **Подзадачи:**
    - [ ] Добавить шаблон "policy review memo".
    - [ ] Зафиксировать mandatory SQL-отчеты для ревью.
    - [ ] Указать как обновлять thresholds безопасно (изменение + soak).

- [ ] **I2-E5-T3: Закрытие итерации и подготовка к следующему этапу**
  - **Цель:** формально закрыть итерацию и зафиксировать выводы.
  - **Файлы:** `TODO-2.md` (эта секция), `REPORT.md`, при необходимости `TODO.md`.
  - **Критерий готовности:** все пункты DoD закрыты, residual risks и backlog улучшений задокументированы.
  - **Тесты/валидация:** полный прогон тестов + smoke сценарий в выбранном целевом режиме.
  - **Риски:** неполный handoff создаст технический долг для следующей итерации.
  - **Зависимости:** все задачи Iteration 2.
  - **Подзадачи:**
    - [ ] Обновить статус в `REPORT.md`.
    - [ ] Сформировать backlog post-enforcement improvements.
    - [ ] Зафиксировать lessons learned по policy quality.

---

## Definition of Done — Iteration 2

Итерация считается завершенной, если одновременно выполнены все условия:

- [ ] Strategy engine работает в трех режимах (`shadow`, `advisory`, `enforcement`) с документированными переходами и rollback.
- [ ] Policy thresholds и budgets конфигурируются через YAML/env, валидируются и применяются в runtime.
- [ ] Каждое решение и его outcome сохраняются в decision log с корреляцией к исполнению.
- [ ] KPI-калибровка выполнена на baseline данных, thresholds обоснованы и подтверждены dry-run сценарием.
- [ ] Enforcement включается по rollout-чеклисту и имеет аварийный downgrade path.
- [ ] Тестовый контур (unit + integration smoke) покрывает режимы стратегии, budgets, logging и calibration.
- [ ] Операционная документация содержит регулярный governance-процесс пересмотра policy.

## Выходные артефакты итерации

- Новый/обновленный runtime-слой стратегии (`src/strategy_engine.py`, `src/policy_engine.py`, интеграция в `src/main.py`).
- Расширенные схемы и методы БД для decision logging.
- Обновленные конфиги policy/threshold/budgets.
- Тесты стратегии и policy в `tests/`.
- Обновленные `docs/OPS.md`, `README.md`, `REPORT.md` с rollout и governance.
