# config/__init__.py
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

def get_os() -> str:
    """Returns: 'windows' | 'mac' | 'linux'"""
    # Prefer environment variable
    env_os = os.getenv("OS_SYSTEM")
    if env_os:
        return env_os.lower()
    
    # Default to platform detection if possible
    import platform
    sys_os = platform.system().lower()
    if sys_os == "darwin": return "mac"
    return sys_os

def is_windows() -> bool: return get_os() == "windows"
def is_mac()     -> bool: return get_os() == "mac"
def is_linux()   -> bool: return get_os() == "linux"