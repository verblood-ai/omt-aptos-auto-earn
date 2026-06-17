# Liquidswap (DEX) — адреса и проверка модулей

## Эталонная сеть (DEX)

В репозитории по умолчанию зафиксирована **`testnet`**: пакеты Liquidswap V2 стабильнее, чем на `devnet`, где после reset список опубликованных модулей по адресу из ветки `devnet-addresses` часто пустой. Газ для свопа по-прежнему только из нативного APT (первый APT — с крана; нюансы testnet/devnet см. **[docs/OPS.md](OPS.md)** и [README](../README.md)).

## Проверенные адреса (REST fullnode)

**Дата проверки:** 2026-04-20.

| Роль | Адрес (testnet) | Источник |
|------|-----------------|----------|
| Пакет Liquidswap (модули `scripts_v2`, `router_v2`, `curves`, …) | `0x190d44266241744264b964a37b8f09863167a12d3e70cda39376cfb4e3561e12` | [Liquidswap — Smart Contracts](https://docs.liquidswap.com/smart-contracts), `Move.toml` ветки `main` репозитория [pontem-network/liquidswap](https://github.com/pontem-network/liquidswap) |
| Ресурсный аккаунт пулов / LP | `0x05a97986a9d031c4567e15b797be516910cfcb4156312482efc6a19c0a30c948` | Там же (раздел *Addresses*) |
| Тестовые монеты Pontem (`coins::USDT` и др.) | `0x43417434fd869edee76cca2a4d2301e528a1551b1d719b75c350c3c97d15b8b9` | Тот же документ: примеры пулов ссылаются на `…::coins::USDT` у этого аккаунта; на testnet по `GET …/accounts/{addr}/modules` присутствует модуль `coins`. |

### Как воспроизвести проверку модулей

```http
GET https://fullnode.testnet.aptoslabs.com/v1/accounts/0x190d44266241744264b964a37b8f09863167a12d3e70cda39376cfb4e3561e12/modules
```

В каждом элементе массива поле `abi.name` должно содержать как минимум **`scripts_v2`** и **`router_v2`** (роутер для вызовов и котировок в коде).

Утилита без отправки транзакций:

```bash
python3 -m src.dex_diagnostics --check-modules
```

## Devnet

Официальная ветка с адресами под reset: [devnet-addresses / Move.toml](https://github.com/pontem-network/liquidswap/blob/devnet-addresses/Move.toml). После сброса devnet **обязательно** повторите проверку `GET …/modules` по актуальному адресу из этой ветки: при пустом ответе `[]` свопы дадут linker error до повторной публикации пакетов.

## Замечания по котировке

`router_v2::get_amount_out` в опубликованном пакете **не помечен как `#[view]`**, поэтому вызов через REST `/view` от fullnode возвращает ошибку. В `activity_dex_swap` оценка выхода и фактический `min_out` опираются на **симуляцию** транзакции и разбор событий депозита монеты (см. код модуля).
