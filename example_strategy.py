"""
Example Trading Strategy Script for Groww Trading System
Demonstrates how to:
1. Connect using your stored keys / TOTP
2. Check real-time portfolio balance & margin
3. Fetch user holdings
4. Check open positions
5. Place algorithmic orders
"""

from growwapi import GrowwAPI
from config import load_credentials


def main():
    print("[*] Loading credentials from keys.txt...")
    creds = load_credentials()
    api_key = creds.get("api_key")
    api_secret = creds.get("api_secret")

    if not api_key:
        print("[!] Error: api_key not found in keys.txt!")
        return

    print("[*] Authenticating with Groww...")
    # Obtain access token
    token = GrowwAPI.get_access_token(api_key=api_key, secret=api_secret)
    client = GrowwAPI(token)

    # 1. Profile
    profile = client.get_user_profile()
    print(f"[+] Connected! UCC: {profile.get('ucc')}, Segments: {profile.get('active_segments')}")

    # 2. Check Margin & Available Cash
    margins = client.get_available_margin_details()
    clear_cash = margins.get("clear_cash", 0.0)
    print(f"[+] Available Clear Cash: Rs. {clear_cash:,.2f}")

    # 3. Check Holdings
    holdings_data = client.get_holdings_for_user()
    holdings = holdings_data.get("holdings", [])
    print(f"[+] Current Demat Holdings ({len(holdings)} stocks):")
    for h in holdings:
        print(f"    - {h.get('trading_symbol')}: Qty {h.get('quantity')} @ Rs. {h.get('average_price')}")

    # 4. Check Open Positions
    pos_data = client.get_positions_for_user()
    positions = pos_data.get("positions", [])
    print(f"[+] Open Positions: {len(positions)}")

    # 5. Place an Order (Example - commented out for safety)
    """
    print("[*] Placing test CNC Buy Order for 1 share of ITC...")
    order = client.place_order(
        trading_symbol="ITC",
        exchange=GrowwAPI.EXCHANGE_NSE,
        transaction_type=GrowwAPI.TRANSACTION_TYPE_BUY,
        order_type=GrowwAPI.ORDER_TYPE_LIMIT,
        quantity=1,
        price=280.0,
        product=GrowwAPI.PRODUCT_CNC,
        validity=GrowwAPI.VALIDITY_DAY
    )
    print("[+] Order placed successfully:", order)
    """


if __name__ == "__main__":
    main()
