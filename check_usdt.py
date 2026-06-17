#!/usr/bin/env python3
import asyncio
import sys
from src.wallet import WalletManager

async def main():
    wm = WalletManager()
    await wm.load_or_create_wallet()

    # USDT asset type on devnet
    usdt_asset_type = '0xf22bede237a07e121b56d91a491eb7bcdfd1f5907926a9e58338f964a01b17fa::asset::USDT'

    try:
        balance = await wm.rest_client.account_balance(wm.account.address(), usdt_asset_type)
        print(f'USDT balance (octas): {balance}')
        print(f'USDT balance (USDT): {float(balance) / 100_000_000}')
    except Exception as e:
        print(f'Error checking USDT balance: {e}')
    finally:
        await wm.rest_client.close()

if __name__ == '__main__':
    asyncio.run(main())
