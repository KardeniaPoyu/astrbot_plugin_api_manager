import asyncio
import logging
import sys
import os

# Add current directory to path so we can import .api_service
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from api_service import ApiService

async def main():
    logging.basicConfig(level=logging.INFO)
    
    # This is a test script for the developer/user to verify their keys
    # Usage: python test_api_mgr.py <provider_type> <api_key> [base_url]
    
    if len(sys.argv) < 3:
        print("Usage: python test_api_mgr.py <provider_type> <api_key> [base_url]")
        print("Example: python test_api_mgr.py siliconflow sk-xxxx")
        return

    provider_type = sys.argv[1]
    api_key = sys.argv[2]
    base_url = sys.argv[3] if len(sys.argv) > 3 else None

    print(f"Testing {provider_type}...")
    result = await ApiService.get_balance(provider_type, api_key, base_url)
    
    if "error" in result:
        print(f"[FAIL] Error: {result['error']}")
    else:
        print(f"[SUCCESS]")
        print(f"   Remaining: {result['remaining']} {result['unit']}")
        print(f"   Total: {result['total']} {result['unit']}")
        print(f"   Used: {result['used']} {result['unit']}")

if __name__ == "__main__":
    asyncio.run(main())
