import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from growwapi import GrowwAPI
import pyotp

from config import Config, load_credentials

logger = logging.getLogger("groww_service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class GrowwService:
    def __init__(self):
        self.api_client: Optional[GrowwAPI] = None
        self.access_token: Optional[str] = None
        self.last_connected_at: Optional[str] = None
        self.token_created_at: Optional[float] = None
        self.profile_cache: Optional[Dict[str, Any]] = None
        self.connection_status: str = "disconnected"  # connected, disconnected, error
        self.last_error: Optional[str] = None

        # Attempt to restore cached session on startup
        self._load_cached_session()

    def _load_cached_session(self):
        """Attempts to restore active token from cache file."""
        cache_file = Config.SESSION_CACHE_FILE
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                token = data.get("access_token")
                created_at = data.get("created_at", 0)

                # Check if token is likely still valid (Groww tokens expire daily at ~6:00 AM IST)
                # If cached within the last 18 hours, test it
                if token and (time.time() - created_at < 18 * 3600):
                    client = GrowwAPI(token)
                    profile = client.get_user_profile()
                    if profile and profile.get("ucc"):
                        self.api_client = client
                        self.access_token = token
                        self.token_created_at = created_at
                        self.last_connected_at = data.get("last_connected_at", datetime.now().isoformat())
                        self.profile_cache = profile
                        self.connection_status = "connected"
                        logger.info("Restored Groww session from local cache successfully.")
                        return
            except Exception as e:
                logger.warning(f"Cached session restoration failed: {e}")

    def _save_cached_session(self):
        """Saves active access token and metadata to cache file."""
        if not self.access_token:
            return
        try:
            data = {
                "access_token": self.access_token,
                "created_at": self.token_created_at or time.time(),
                "last_connected_at": self.last_connected_at or datetime.now().isoformat(),
            }
            with open(Config.SESSION_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save session cache: {e}")

    def _clear_cache(self):
        """Clears local session cache file."""
        if Config.SESSION_CACHE_FILE.exists():
            try:
                Config.SESSION_CACHE_FILE.unlink()
            except Exception:
                pass

    def connect(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        totp_code: Optional[str] = None,
        totp_secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Authenticates with Groww.
        Priority:
          1. If totp_code is provided directly, use API Key + TOTP code.
          2. If totp_secret is provided (seed), generate TOTP using pyotp and use API Key + TOTP code.
          3. If api_secret is provided, use API Key + API Secret checksum approval flow.
          4. If credentials omitted, fall back to keys.txt / key.txt / .env
        """
        self.last_error = None
        saved_creds = load_credentials()

        key = (api_key or saved_creds.get("api_key", "")).strip()
        secret = (api_secret or saved_creds.get("api_secret", "")).strip()
        t_seed = (totp_secret or saved_creds.get("totp_secret", "")).strip()
        t_code = (totp_code or "").strip()

        if not key:
            self.connection_status = "error"
            self.last_error = "Missing API Key. Please provide api_key in keys.txt or via the form."
            return {"success": False, "error": self.last_error}

        token = None
        auth_method_used = None

        # Method A: Direct TOTP 6-digit code
        if t_code:
            try:
                logger.info("Attempting login via direct TOTP code...")
                token = GrowwAPI.get_access_token(api_key=key, totp=t_code)
                auth_method_used = "Manual TOTP Code"
            except Exception as e:
                logger.warning(f"Direct TOTP login failed: {e}")
                self.last_error = f"TOTP verification failed: {str(e)}"

        # Method B: TOTP secret seed with pyotp
        if not token and t_seed:
            try:
                logger.info("Attempting login via pyotp TOTP secret seed...")
                totp_gen = pyotp.TOTP(t_seed)
                generated_totp = totp_gen.now()
                token = GrowwAPI.get_access_token(api_key=key, totp=generated_totp)
                auth_method_used = "Generated TOTP (pyotp)"
            except Exception as e:
                logger.warning(f"pyotp TOTP login failed: {e}")
                if not self.last_error:
                    self.last_error = f"pyotp TOTP generation failed: {str(e)}"

        # Method C: API Secret (checksum approval)
        if not token and secret:
            try:
                logger.info("Attempting login via API Secret checksum approval...")
                token = GrowwAPI.get_access_token(api_key=key, secret=secret)
                auth_method_used = "API Secret"
            except Exception as e:
                logger.warning(f"API Secret login failed: {e}")
                if not self.last_error:
                    self.last_error = f"API Secret login failed: {str(e)}"

        if not token:
            self.connection_status = "error"
            return {
                "success": False,
                "error": self.last_error or "Could not authenticate with Groww. Please check your credentials.",
            }

        try:
            # Instantiate client and verify token by fetching user profile
            client = GrowwAPI(token)
            profile = client.get_user_profile()

            self.api_client = client
            self.access_token = token
            self.token_created_at = time.time()
            self.last_connected_at = datetime.now().isoformat()
            self.profile_cache = profile
            self.connection_status = "connected"
            self.last_error = None

            self._save_cached_session()

            return {
                "success": True,
                "auth_method": auth_method_used,
                "ucc": profile.get("ucc"),
                "profile": profile,
            }
        except Exception as e:
            self.connection_status = "error"
            self.last_error = f"Authenticated token rejected: {str(e)}"
            return {"success": False, "error": self.last_error}

    def disconnect(self):
        """Disconnects current session and clears cache."""
        self.api_client = None
        self.access_token = None
        self.profile_cache = None
        self.connection_status = "disconnected"
        self._clear_cache()
        return {"success": True}

    def get_status(self) -> Dict[str, Any]:
        """Returns current connection status and basic info."""
        creds = load_credentials()
        has_api_key = bool(creds.get("api_key"))
        has_api_secret = bool(creds.get("api_secret"))
        has_totp_secret = bool(creds.get("totp_secret"))

        return {
            "status": self.connection_status,
            "is_connected": self.connection_status == "connected" and self.api_client is not None,
            "last_connected_at": self.last_connected_at,
            "ucc": self.profile_cache.get("ucc") if self.profile_cache else None,
            "has_saved_keys": has_api_key and (has_api_secret or has_totp_secret),
            "masked_api_key": f"{creds['api_key'][:8]}...{creds['api_key'][-6:]}" if has_api_key else None,
            "last_error": self.last_error,
        }

    def get_profile(self) -> Dict[str, Any]:
        """Fetches profile details from Groww."""
        if not self.api_client:
            return {"success": False, "error": "Not connected to Groww. Please connect first."}
        try:
            profile = self.api_client.get_user_profile()
            self.profile_cache = profile
            return {"success": True, "profile": profile}
        except Exception as e:
            logger.error(f"Error fetching profile: {e}")
            return {"success": False, "error": str(e)}

    def get_funds(self) -> Dict[str, Any]:
        """Fetches margin and funds information."""
        if not self.api_client:
            return {"success": False, "error": "Not connected to Groww. Please connect first."}
        try:
            margins = self.api_client.get_available_margin_details()
            return {"success": True, "funds": margins}
        except Exception as e:
            logger.error(f"Error fetching funds: {e}")
            return {"success": False, "error": str(e)}

    def get_holdings(self) -> Dict[str, Any]:
        """Fetches stock holdings and enriches with calculated totals."""
        if not self.api_client:
            return {"success": False, "error": "Not connected to Groww. Please connect first."}
        try:
            res = self.api_client.get_holdings_for_user()
            holdings = res.get("holdings", []) if isinstance(res, dict) else (res or [])

            total_invested = 0.0
            enriched_holdings = []
            for item in holdings:
                qty = float(item.get("quantity", 0))
                avg_price = float(item.get("average_price", 0))
                invested = qty * avg_price
                total_invested += invested

                enriched_item = dict(item)
                enriched_item["invested_value"] = round(invested, 2)
                enriched_holdings.append(enriched_item)

            # Calculate allocation percentages
            for item in enriched_holdings:
                item["allocation_pct"] = (
                    round((item["invested_value"] / total_invested) * 100, 2)
                    if total_invested > 0
                    else 0.0
                )

            return {
                "success": True,
                "holdings": enriched_holdings,
                "count": len(enriched_holdings),
                "total_invested": round(total_invested, 2),
            }
        except Exception as e:
            logger.error(f"Error fetching holdings: {e}")
            return {"success": False, "error": str(e)}

    def get_positions(self) -> Dict[str, Any]:
        """Fetches open / day positions."""
        if not self.api_client:
            return {"success": False, "error": "Not connected to Groww. Please connect first."}
        try:
            res = self.api_client.get_positions_for_user()
            positions = res.get("positions", []) if isinstance(res, dict) else (res or [])
            return {"success": True, "positions": positions, "count": len(positions)}
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return {"success": False, "error": str(e)}

    def get_orders(self) -> Dict[str, Any]:
        """Fetches active and completed orders."""
        if not self.api_client:
            return {"success": False, "error": "Not connected to Groww. Please connect first."}
        try:
            res = self.api_client.get_order_list()
            orders = res.get("order_list", []) if isinstance(res, dict) else (res or [])
            return {"success": True, "orders": orders, "count": len(orders)}
        except Exception as e:
            logger.error(f"Error fetching orders: {e}")
            return {"success": False, "error": str(e)}


# Singleton instance for the application
groww_service = GrowwService()
