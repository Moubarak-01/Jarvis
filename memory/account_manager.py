import json
import base64
import os
import sys
import uuid
from pathlib import Path
from threading import Lock
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR      = get_base_dir()
ACCOUNTS_PATH = BASE_DIR / "memory" / "accounts.json"
_lock         = Lock()

def _get_key() -> bytes:
    """Derives a stable symmetric key from the machine's hardware ID."""
    machine_id = str(uuid.getnode()).encode()
    salt       = b'jarvis_vault_salt_123' # Fixed salt for consistency across reboots
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(machine_id))
    return key

def _encrypt(data: str) -> str:
    f = Fernet(_get_key())
    return f.encrypt(data.encode()).decode()

def _decrypt(token: str) -> str:
    f = Fernet(_get_key())
    return f.decrypt(token.encode()).decode()

def _load_raw() -> dict:
    if not ACCOUNTS_PATH.exists():
        return {}
    try:
        return json.loads(ACCOUNTS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[AccountManager] ⚠️ Load error: {e}")
        return {}

def _save_raw(data: dict) -> None:
    ACCOUNTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        ACCOUNTS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

def add_account(service: str, alias: str, data: dict) -> bool:
    """
    Adds or updates an account. 
    'data' should contain tokens/credentials.
    """
    try:
        raw = _load_raw()
        if service not in raw:
            raw[service] = {}
        
        # Encrypt the entire data block
        encrypted_data = _encrypt(json.dumps(data))
        raw[service][alias] = {
            "payload": encrypted_data,
            "updated": os.urandom(0).hex() # Placeholder for timestamp if needed
        }
        
        _save_raw(raw)
        print(f"[AccountManager] [OK] Added {service}/{alias}")
        return True
    except Exception as e:
        print(f"[AccountManager] [ERROR] Add error: {e}")
        return False

def get_account(service: str, alias: str) -> dict | None:
    """Retrieves and decrypts account data."""
    raw = _load_raw()
    account = raw.get(service, {}).get(alias)
    if not account:
        return None
    
    try:
        decrypted = _decrypt(account["payload"])
        return json.loads(decrypted)
    except Exception as e:
        print(f"[AccountManager] [ERROR] Decrypt error for {service}/{alias}: {e}")
        return None

def list_accounts(service: str = None) -> dict:
    """Returns a list of all accounts, or accounts for a specific service."""
    raw = _load_raw()
    if service:
        return list(raw.get(service, {}).keys())
    
    result = {}
    for svc, aliases in raw.items():
        result[svc] = list(aliases.keys())
    return result

def delete_account(service: str, alias: str) -> bool:
    raw = _load_raw()
    if service in raw and alias in raw[service]:
        del raw[service][alias]
        if not raw[service]:
            del raw[service]
        _save_raw(raw)
        return True
    return False

if __name__ == "__main__":
    # Quick test
    test_data = {"token": "secret_123", "user": "ali"}
    add_account("test_svc", "default", test_data)
    retrieved = get_account("test_svc", "default")
    print(f"Retrieved: {retrieved}")
    if retrieved == test_data:
        print("Test Passed!")
    else:
        print("Test Failed!")
