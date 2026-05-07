import os
import sys
from pathlib import Path


def _get_startup_folder() -> Path:
    return Path(os.getenv("APPDATA")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _get_python_exe() -> str:
    """Always return python.exe, never pythonw.exe.

    pythonw.exe is windowless — child processes that need a console each
    get a *new* console window, which causes the rapid-fire terminal
    flashing on boot / wake.  Using regular python.exe ensures everything
    shares one stable terminal, identical to double-clicking Jarvis.bat.
    """
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        exe = exe[:-5] + ".exe"          # pythonw.exe → python.exe
    return exe


def _cleanup_legacy(startup_folder: Path):
    """Remove any leftover .lnk shortcut from a previous setup."""
    for legacy in ("JarvisMark39.lnk", "Jarvis.lnk"):
        old = startup_folder / legacy
        if old.exists():
            try:
                old.unlink()
            except OSError:
                pass


def setup_startup():
    """Adds JARVIS to Windows startup.

    Places a .bat file in the shell:Startup folder that is functionally
    identical to the project's Jarvis.bat — one terminal, one process.
    """
    if sys.platform != "win32":
        return "Startup automation is only supported on Windows, sir."

    try:
        startup_folder = _get_startup_folder()
        bat_path       = startup_folder / "Jarvis.bat"

        project_dir = Path(__file__).resolve().parent.parent
        main_py     = project_dir / "main.py"
        python_exe  = _get_python_exe()

        # Remove any old .lnk shortcuts that used pythonw.exe
        _cleanup_legacy(startup_folder)

        # Write a bat identical to double-clicking Jarvis.bat
        bat_content = (
            '@echo off\n'
            'title JARVIS Mark-XXXIX\n'
            f'cd /d "{project_dir}"\n'
            'echo [SYSTEM] Starting JARVIS...\n'
            f'"{python_exe}" "{main_py}"\n'
            'pause\n'
        )

        bat_path.write_text(bat_content, encoding="utf-8")
        return (
            f"I've added JARVIS to your startup folder, sir. "
            f"It will now boot up with your computer. (Path: {bat_path})"
        )
    except Exception as e:
        return f"I encountered an error while setting up startup: {e}"


def remove_startup():
    """Removes JARVIS from Windows startup."""
    if sys.platform != "win32":
        return "Startup automation is only supported on Windows, sir."

    try:
        startup_folder = _get_startup_folder()
        removed = False

        # Remove both .bat and any legacy .lnk files
        for name in ("Jarvis.bat", "JarvisMark39.lnk", "Jarvis.lnk"):
            target = startup_folder / name
            if target.exists():
                target.unlink()
                removed = True

        if removed:
            return "I've removed JARVIS from your startup folder, sir."
        else:
            return "JARVIS was not in your startup folder, sir."
    except Exception as e:
        return f"I encountered an error while removing from startup: {e}"
