import json
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR    = get_base_dir()
CONFIG_DIR  = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "api_keys.json"

def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def config_exists() -> bool:
    return CONFIG_FILE.exists()

def save_api_keys(gemini_api_key: str) -> None:
    ensure_config_dir()

    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    data["gemini_api_key"] = gemini_api_key.strip()

    CONFIG_FILE.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8"
    )

def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Failed to load config: {e}")
        return {}

def save_config_key(key: str, value) -> None:
    ensure_config_dir()
    data = load_config()
    data[key] = value
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

def get_gemini_key() -> str | None:
    # 1. Try environment variable
    env_key = os.getenv("GEMINI_API_KEY")
    if env_key:
        return env_key

    # 2. Try JSON config
    return load_config().get("gemini_api_key")

def get_os_system() -> str:
    # 1. Try environment variable
    env_os = os.getenv("OS_SYSTEM")
    if env_os:
        return env_os.lower()

    # 2. Try JSON config
    return load_config().get("os_system", "windows").lower()

def is_configured() -> bool:
    key = get_gemini_key()
    return bool(key and len(key) > 15)