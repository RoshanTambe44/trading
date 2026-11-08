import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Load .env if present
load_dotenv(BASE_DIR / ".env")


def load_credentials():
    """
    Loads API credentials from keys.txt, key.txt, or environment variables.
    Supports keys formatted as:
      api_key = <key>
      api_secret = <secret>
      totp_secret = <totp_seed> (optional)
    """
    credentials = {
        "api_key": os.getenv("GROWW_API_KEY", ""),
        "api_secret": os.getenv("GROWW_API_SECRET", ""),
        "totp_secret": os.getenv("GROWW_TOTP_SECRET", ""),
    }

    # Candidates for key files
    key_files = [
        BASE_DIR / "keys.txt",
        BASE_DIR / "key.txt",
        Path.home() / "Groww-Trading-Project" / "keys.txt",
        Path.home() / "Groww-Trading-Project" / "key.txt",
    ]

    for key_file in key_files:
        if key_file.exists() and key_file.is_file():
            try:
                with open(key_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip().lower()
                            v = v.strip().strip('"').strip("'")
                            if k in ["api_key", "groww_api_key"]:
                                credentials["api_key"] = v
                            elif k in ["api_secret", "groww_api_secret", "secret"]:
                                credentials["api_secret"] = v
                            elif k in ["totp_secret", "totp_key", "totp"]:
                                credentials["totp_secret"] = v
                if credentials["api_key"]:
                    break
            except Exception as e:
                print(f"[Config] Error reading {key_file}: {e}")

    return credentials


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "groww-trading-terminal-secret-key-2026")
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", 5000))
    DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "yes")
    SESSION_CACHE_FILE = BASE_DIR / ".session_cache.json"
