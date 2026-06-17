#!/usr/bin/env python3
"""Simple test for DEX swap transaction building."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from aptos_sdk.type_tag import TypeTag, StructTag
from aptos_sdk.transactions import EntryFunction, TransactionArgument, Serializer

def test_build_entry_function():
    """Test building the swap entry function."""
    
    # Configuration
    router_address = "0x43417434fd869edee76cca2a4d2301e528a1551b1d719b75c350c3c97d15b8b9"
    from_token = "0x1::aptos_coin::AptosCoin"
    to_token = "0xf22bede237a07e121b56d91a491eb7bcdfd1f5907926a9e58338f964a01b17fa::asset::USDT"
    amount = 1_000_000  # 0.01 APT in octas
    min_out = 2_500_000  # ~0.025 USDT (6 decimals)
    
    # Sort tokens lexicographically
    tokens = sorted([from_token, to_token], key=lambda s: s.lower())
    print(f"Sorted tokens: {tokens}")
    
    token_x = StructTag.from_str(tokens[0])
    token_y = StructTag.from_str(tokens[1])
    
    # Curve type
    curve_tag = StructTag.from_str(f"{router_address}::curves::Uncorrelated")
    
    # Type arguments
    type_args = [TypeTag(token_x), TypeTag(token_y), TypeTag(curve_tag)]
    print(f"Type args: {[str(t) for t in type_args]}")
    
    # Build entry function
    module = f"{router_address}::scripts_v2"
    function = "swap"
    
    entry_func = EntryFunction.natural(
        module=module,
        function=function,
        ty_args=type_args,
        args=[
            TransactionArgument(amount, Serializer.u64),
            TransactionArgument(min_out, Serializer.u64)
        ]
    )
    
    print(f"Entry function created:")
    print(f"  Module: {entry_func.module}")
    print(f"  Function: {entry_func.function}")
    print(f"  Type args count: {len(entry_func.ty_args)}")
    print(f"  Args count: {len(entry_func.args)}")
    
    # Try to serialize
    try:
        from aptos_sdk.bcs import Serializer as BcsSerializer
        serializer = BcsSerializer()
        entry_func.serialize(serializer)
        bytes_data = serializer.output()  # Get the buffer bytes
        print(f"Serialization successful! BCS bytes length: {len(bytes_data)}")
        print(f"First 20 bytes (hex): {bytes_data[:20].hex()}")
    except Exception as e:
        print(f"Serialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    success = test_build_entry_function()
    sys.exit(0 if success else 1)
