
from __future__ import annotations

import asyncio
import concurrent.futures
import os
import platform
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeout,
)
_OS = platform.system()   # "Windows" | "Darwin" | "Linux"

def _normalize_url(url: str) -> str:
    """
    Bare words like "instagram" → "https://instagram.com"
    Domains like "instagram.com" → "https://instagram.com"
    Full URLs pass through unchanged.
    """
    url = url.strip()
    if not url:
        return "about:blank"
    if "://" in url:
        return url
    # No dot at all → assume .com  (e.g. "instagram" → "instagram.com")
    if "." not in url:
        url = url + ".com"
    return "https://" + url


def _user_agent() -> str:
    if _OS == "Windows":
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    if _OS == "Darwin":
        return (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    return (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )


def _real_profile_dir(browser: str) -> str:
    home  = Path.home()
    local = os.environ.get("LOCALAPPDATA", "")
    roam  = os.environ.get("APPDATA", "")

    candidates: list[Path] = []

    if _OS == "Windows":
        m = {
            "chrome":   [Path(local) / "Google"          / "Chrome"          / "User Data" / "Default"],
            "edge":     [Path(local) / "Microsoft"        / "Edge"            / "User Data" / "Default"],
            "brave":    [Path(local) / "BraveSoftware"    / "Brave-Browser"   / "User Data" / "Default"],
            "vivaldi":  [Path(local) / "Vivaldi"          / "User Data" / "Default"],
            "opera":    [Path(roam)  / "Opera Software"   / "Opera Stable",
                         Path(local) / "Opera Software"   / "Opera Stable"],
            "operagx":  [Path(roam)  / "Opera Software"   / "Opera GX Stable",
                         Path(local) / "Opera Software"   / "Opera GX Stable"],
        }
        candidates = m.get(browser, [])

    elif _OS == "Darwin":
        lib = home / "Library" / "Application Support"
        m = {
            "chrome":   [lib / "Google"             / "Chrome" / "Default"],
            "edge":     [lib / "Microsoft Edge" / "Default"],
            "brave":    [lib / "BraveSoftware"       / "Brave-Browser" / "Default"],
            "vivaldi":  [lib / "Vivaldi" / "Default"],
            "opera":    [lib / "com.operasoftware.Opera"],
            "operagx":  [lib / "com.operasoftware.OperaGX"],
        }
        candidates = m.get(browser, [])

    elif _OS == "Linux":
        cfg = home / ".config"
        m = {
            "chrome":   [cfg / "google-chrome" / "Default", cfg / "chromium" / "Default"],
            "edge":     [cfg / "microsoft-edge" / "Default"],
            "brave":    [cfg / "BraveSoftware" / "Brave-Browser" / "Default"],
            "vivaldi":  [cfg / "vivaldi" / "Default"],
            "opera":    [cfg / "opera"],
            "operagx":  [cfg / "opera-gx"],
        }
        candidates = m.get(browser, [])

    for p in candidates:
        if p.exists():
            print(f"[Browser] ✅ Real profile found for {browser}: {p}")
            return str(p)

    fallback = home / ".jarvis_profiles" / browser
    fallback.mkdir(parents=True, exist_ok=True)
    print(f"[Browser] ⚠️  Real profile not found for {browser}, using: {fallback}")
    return str(fallback)

def _firefox_profile_dir() -> Optional[str]:
    home = Path.home()

    if _OS == "Windows":
        base = Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox"
    elif _OS == "Darwin":
        base = home / "Library" / "Application Support" / "Firefox"
    else:
        base = home / ".mozilla" / "firefox"

    ini = base / "profiles.ini"
    if not ini.exists():
        return None

    current: dict[str, str] = {}
    default_path: Optional[str] = None

    for line in ini.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("["):
            p = current.get("Path", "")
            if p and current.get("Default") == "1":
                is_rel = current.get("IsRelative", "1") == "1"
                default_path = str(base / p) if is_rel else p
            current = {}
        elif "=" in line:
            k, _, v = line.partition("=")
            current[k.strip()] = v.strip()

    p = current.get("Path", "")
    if p and current.get("Default") == "1":
        is_rel = current.get("IsRelative", "1") == "1"
        default_path = str(base / p) if is_rel else p

    if default_path and Path(default_path).exists():
        print(f"[Browser] Firefox real profile: {default_path}")
        return default_path
    return None

def _find_opera_windows() -> Optional[str]:
    local  = os.environ.get("LOCALAPPDATA", "")
    prog   = os.environ.get("PROGRAMFILES", "")
    prog86 = os.environ.get("PROGRAMFILES(X86)", "")

    candidates = [
        Path(local)  / "Programs" / "Opera"    / "opera.exe",
        Path(local)  / "Programs" / "Opera GX" / "opera.exe",
        Path(prog)   / "Opera"    / "opera.exe",
        Path(prog86) / "Opera"    / "opera.exe",
    ]
    for p in candidates:
        if p.exists():
            print(f"[Browser] Opera found at: {p}")
            return str(p)

    try:
        import winreg
        keys = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\opera.exe",
            r"SOFTWARE\Clients\StartMenuInternet\OperaStable\shell\open\command",
            r"SOFTWARE\Clients\StartMenuInternet\OperaGXStable\shell\open\command",
            r"SOFTWARE\Clients\StartMenuInternet\opera\shell\open\command",
        ]
        for key_path in keys:
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    k   = winreg.OpenKey(hive, key_path)
                    val = winreg.QueryValue(k, None)
                    winreg.CloseKey(k)
                    exe = val.strip().strip('"').split('"')[0].split(" --")[0].strip()
                    if exe and Path(exe).exists():
                        print(f"[Browser] Opera found via registry: {exe}")
                        return exe
                except Exception:
                    continue
    except Exception:
        pass

    return shutil.which("opera") or None

def _find_exe_windows(prog_name: str) -> Optional[str]:
    try:
        import winreg
        paths_to_try = [
            rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{prog_name}.exe",
            rf"SOFTWARE\Clients\StartMenuInternet\{prog_name}\shell\open\command",
        ]
        for key_path in paths_to_try:
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    k   = winreg.OpenKey(hive, key_path)
                    val = winreg.QueryValue(k, None)
                    winreg.CloseKey(k)
                    exe = val.strip().strip('"').split('"')[0].split(" --")[0].strip()
                    if exe and Path(exe).exists():
                        return exe
                except Exception:
                    continue
    except Exception:
        pass
    return None

_BROWSER_SPECS: dict[str, dict] = {
    "Windows": {
        "chrome":   {"engine": "chromium", "channel": "chrome",  "bins": []},
        "edge":     {"engine": "chromium", "channel": "msedge",  "bins": []},
        "firefox":  {"engine": "firefox",  "channel": None,      "bins": ["firefox.exe"]},
        "opera":    {"engine": "chromium", "channel": None,      "bins": ["opera.exe"],  "special": "opera_windows"},
        "operagx":  {"engine": "chromium", "channel": None,      "bins": [],             "special": "opera_windows"},
        "brave":    {"engine": "chromium", "channel": None,      "bins": ["brave.exe"]},
        "vivaldi":  {"engine": "chromium", "channel": None,      "bins": ["vivaldi.exe"]},
        "safari":   None,
    },
    "Darwin": {
        "chrome":   {"engine": "chromium", "channel": "chrome",  "bins": []},
        "edge":     {"engine": "chromium", "channel": "msedge",  "bins": ["microsoft-edge"]},
        "firefox":  {"engine": "firefox",  "channel": None,      "bins": ["firefox"]},
        "opera":    {"engine": "chromium", "channel": None,      "bins": ["opera"]},
        "operagx":  {"engine": "chromium", "channel": None,      "bins": ["opera"]},
        "brave":    {"engine": "chromium", "channel": None,      "bins": ["brave browser", "brave"]},
        "vivaldi":  {"engine": "chromium", "channel": None,      "bins": ["vivaldi"]},
        "safari":   {"engine": "webkit",   "channel": None,      "bins": []},
    },
    "Linux": {
        "chrome":   {"engine": "chromium", "channel": None,
                     "bins": ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"]},
        "edge":     {"engine": "chromium", "channel": None,
                     "bins": ["microsoft-edge", "microsoft-edge-stable"]},
        "firefox":  {"engine": "firefox",  "channel": None, "bins": ["firefox"]},
        "opera":    {"engine": "chromium", "channel": None, "bins": ["opera", "opera-stable"]},
        "operagx":  {"engine": "chromium", "channel": None, "bins": ["opera", "opera-stable"]},
        "brave":    {"engine": "chromium", "channel": None, "bins": ["brave-browser", "brave"]},
        "vivaldi":  {"engine": "chromium", "channel": None, "bins": ["vivaldi-stable", "vivaldi"]},
        "safari":   None,
    },
}

_ALIASES: dict[str, str] = {
    "google chrome":   "chrome",
    "google-chrome":   "chrome",
    "microsoft edge":  "edge",
    "ms edge":         "edge",
    "msedge":          "edge",
    "mozilla firefox": "firefox",
    "opera gx":        "operagx",
    "opera_gx":        "operagx",
}


def _resolve_browser(name: str) -> dict | None:
    name   = _ALIASES.get(name.lower().strip(), name.lower().strip())
    os_map = _BROWSER_SPECS.get(_OS, {})
    spec   = os_map.get(name)
    if spec is None:
        return None

    engine  = spec["engine"]
    channel = spec.get("channel")
    bins    = spec.get("bins", [])
    exe     = None

    if spec.get("special") == "opera_windows":
        exe = _find_opera_windows()
        if not exe:
            print(f"[Browser] ⚠️  Opera executable not found on Windows.")
        return {"engine": engine, "exe": exe, "channel": channel}

    for b in bins:
        found = shutil.which(b)
        if found:
            exe = found
            break

    if not exe and _OS == "Darwin":
        app_names = {
            "chrome":  ["Google Chrome.app"],
            "edge":    ["Microsoft Edge.app"],
            "firefox": ["Firefox.app"],
            "opera":   ["Opera.app", "Opera GX.app"],
            "brave":   ["Brave Browser.app"],
            "vivaldi": ["Vivaldi.app"],
        }
        for app in app_names.get(name, []):
            app_dir = Path("/Applications") / app / "Contents" / "MacOS"
            if app_dir.exists():
                found_bins = list(app_dir.iterdir())
                if found_bins:
                    exe = str(found_bins[0])
                    break

    if not exe and _OS == "Windows" and not channel:
        exe = _find_exe_windows(name)

    return {"engine": engine, "exe": exe, "channel": channel}


def _detect_default_browser() -> str:
    try:
        if _OS == "Windows":
            import winreg
            k = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations"
                r"\UrlAssociations\http\UserChoice",
            )
            prog_id = winreg.QueryValueEx(k, "ProgId")[0].lower()
            winreg.CloseKey(k)
            for kw in ("edge", "firefox", "opera", "brave", "vivaldi", "chrome"):
                if kw in prog_id:
                    return kw
        elif _OS == "Darwin":
            out = subprocess.run(
                ["defaults", "read",
                 "com.apple.LaunchServices/com.apple.launchservices.secure",
                 "LSHandlers"],
                capture_output=True, text=True, timeout=5,
            ).stdout.lower()
            for kw in ("firefox", "opera", "brave", "vivaldi", "safari", "chrome", "edge"):
                if kw in out:
                    return kw
        elif _OS == "Linux":
            out = subprocess.run(
                ["xdg-settings", "get", "default-web-browser"],
                capture_output=True, text=True, timeout=5,
            ).stdout.lower()
            for kw in ("firefox", "opera", "brave", "vivaldi", "chrome", "edge"):
                if kw in out:
                    return kw
    except Exception:
        pass
    return "chrome"


class _BrowserSession:
    """
    Bir tarayıcı örneği için tam oturum.
    Tüm tarayıcılar launch_persistent_context ile gerçek profil üzerinde açılır.
    """

    def __init__(self, browser_name: str):
        self.browser_name = browser_name
        self._spec        = _resolve_browser(browser_name)
        self._loop:    asyncio.AbstractEventLoop | None = None
        self._thread:  threading.Thread | None          = None
        self._ready    = threading.Event()

        self._browser: Optional[Browser] = None
        self._context: BrowserContext | None = None
        self._page:    Page           | None = None
        self._pw:      Playwright     | None = None
        self._use_fallback_profile: bool = False

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=f"BrowserThread-{self.browser_name}",
        )
        self._thread.start()
        self._ready.wait(timeout=20)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._async_init())
        self._ready.set()
        self._loop.run_forever()

    async def _async_init(self):
        self._pw = await async_playwright().start()

    def run(self, coro, timeout: int = 60) -> str:
        if not self._loop:
            raise RuntimeError(f"Session for '{self.browser_name}' not started.")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def close(self):
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._async_close(), self._loop).result(10)

    async def _async_close(self):
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._context = self._page = None

    async def _launch(self):
        """
        Tarayıcıyı gerçek kullanıcı profiliyle başlatır.
        Context zaten açıksa hiçbir şey yapmaz.
        """
        if self._context is not None:
            return

        if self._spec is None:
            raise RuntimeError(
                f"'{self.browser_name}' bu platformda ({_OS}) desteklenmiyor."
            )

        engine_name = self._spec["engine"]
        exe         = self._spec["exe"]
        channel     = self._spec["channel"]
        engine_obj  = getattr(self._pw, engine_name)

        if engine_name == "firefox":
            profile = _firefox_profile_dir() or str(
                Path.home() / ".jarvis_profiles" / "firefox"
            )
            kwargs: dict = {
                "headless":    False,
                "slow_mo":     0,
                "viewport":    None,
                "no_viewport": True,
            }
            if exe:
                kwargs["executable_path"] = exe
            try:
                self._context = await engine_obj.launch_persistent_context(profile, **kwargs)
            except Exception as e:
                print(f"[Browser] Firefox real profile failed ({e}), using JARVIS profile")
                jarvis = str(Path.home() / ".jarvis_profiles" / "firefox_jarvis")
                Path(jarvis).mkdir(parents=True, exist_ok=True)
                self._context = await engine_obj.launch_persistent_context(jarvis, **kwargs)

            await asyncio.sleep(0.2)  
            self._page = await self._context.new_page()
            print(f"[Browser] ✅ Firefox launched")
            return

        if engine_name == "webkit":
            safari_profile = str(Path.home() / ".jarvis_profiles" / "safari")
            Path(safari_profile).mkdir(parents=True, exist_ok=True)
            kwargs = {
                "headless":    False,
                "slow_mo":     0,
                "viewport":    None,
                "no_viewport": True,
            }
            self._context = await engine_obj.launch_persistent_context(safari_profile, **kwargs)
            await asyncio.sleep(0.2)
            self._page = await self._context.new_page()
            print(f"[Browser] ✅ Safari launched")
            return

        # --- Profile Selection ---
        if self._use_fallback_profile:
            print(f"[Browser] 🛡️ Using JARVIS safety profile (Real profile is locked).")
            profile = str(Path.home() / ".jarvis_profiles" / f"{self.browser_name}_jarvis")
        else:
            profile = _real_profile_dir(self.browser_name)

        kwargs = {
            "headless":    False,
            "slow_mo":     0,
            "viewport":    None,
            "no_viewport": True,
            "args": [
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--disable-default-apps",
                "--no-default-browser-check",
                "--profile-directory=Default",
            ],
        }

        if exe:
            kwargs["executable_path"] = exe
        elif channel:
            kwargs["channel"] = channel

        label = (
            f"{self.browser_name}"
            + (f"/{channel}" if channel else "")
            + (f" @ {exe}" if exe else "")
        )

        try:
            # 1. Instant Profile Lock Detection (Zero Timeout)
            if _OS == "Windows":
                # The lock file is usually in the parent of the 'Default' profile folder
                p_path = Path(profile)
                lock_file = p_path.parent / "SingletonLock" if p_path.name == "Default" else p_path / "SingletonLock"
                
                if lock_file.exists():
                    try:
                        # Try to rename the file to itself. This fails instantly if another process (Chrome) has it open.
                        # This is much more reliable on Windows than os.open.
                        lock_file.rename(lock_file)
                    except (PermissionError, OSError):
                        print(f"[Browser] 🛡️ Detected lock on '{self.browser_name}' profile instantly.")
                        if not self._use_fallback_profile:
                            self._use_fallback_profile = True
                            await self._launch()
                            return

            self._context = await engine_obj.launch_persistent_context(profile, **kwargs)
            await asyncio.sleep(0.1) 
            
            # --- CRITICAL CHECK: Verify if the browser actually stayed alive ---
            if not self._context.pages:
                self._page = await self._context.new_page()
            else:
                self._page = self._context.pages[0]

            print(f"[Browser] ✅ Launched [{label}] profile={profile}")
            return
        except Exception as e:
            if not self._use_fallback_profile:
                print(f"[Browser] ⚠️ Real profile failed or crashed for {label}: {e}")
                print(f"[Browser] 🛡️ Blacklisting real profile and switching to safety profile for this session.")
                self._use_fallback_profile = True
                # Clean up and try again
                if self._context:
                    try: await self._context.close()
                    except: pass
                self._context = None
                await self._launch()
                return
            else:
                print(f"[Browser] ❌ Safety profile also failed: {e}")
                raise e


    async def _get_page(self) -> Page:
        await self._launch()
        
        # If context is dead, we must perform a hard reset and relaunch
        context_is_dead = False
        try:
            if self._context:
                # Simple check to see if context is still responsive
                _ = self._context.pages[0].url if self._context.pages else "about:blank"
        except Exception:
            context_is_dead = True

        if context_is_dead:
            print("[Browser] ⚠️ Detected dead browser context. Performing hard reset...")
            try:
                if self._context: await self._context.close()
            except: pass
            self._context = None
            self._page = None
            await self._launch()

        # If somehow page got closed, open a fresh one
        if self._page is None or self._page.is_closed():
            try:
                self._page = await self._context.new_page()
                await asyncio.sleep(0.2)
            except Exception as e:
                print(f"[Browser] ❌ Failed to open new page: {e}. Attempting one last recovery...")
                self._context = None
                self._page = None
                await self._launch()
                self._page = await self._context.new_page()
                
        return self._page

    async def go_to(self, url: str) -> str:

        url      = _normalize_url(url)
        page     = await self._get_page()
        prev_url = page.url

        async def _do_goto(p: Page) -> str:
            """Attempt navigation and return the resulting URL (may still be blank)."""
            try:
                await p.goto(url, wait_until="domcontentloaded", timeout=30_000)
                await asyncio.sleep(0.3)
            except PlaywrightTimeout:
                pass   # page may have partially loaded — check URL below
            except Exception as e:
                print(f"[Browser] goto exception (non-fatal): {e}")
            return p.url

        result_url = await _do_goto(page)

        if result_url in ("about:blank", "", None, prev_url) and prev_url in ("about:blank", "", None):
            print(f"[Browser] Still blank after goto — retrying on new tab: {url}")
            try:
                new_page   = await self._context.new_page()
                self._page = new_page
                result_url = await _do_goto(new_page)
            except Exception as e:
                print(f"[Browser] New-tab retry failed: {e}")

        if result_url and result_url not in ("about:blank", "", None):
            return f"Opened: {result_url}"
        return f"Could not open: {url}"

    async def search(self, query: str, engine: str = "google") -> str:
        _engines = {
            "google":     "https://www.google.com/search?q=",
            "bing":       "https://www.bing.com/search?q=",
            "duckduckgo": "https://duckduckgo.com/?q=",
            "yandex":     "https://yandex.com/search/?text=",
            "youtube":    "https://www.youtube.com/results?search_query=",
            "wikipedia":  "https://en.wikipedia.org/wiki/Special:Search?search=",
            "github":     "https://github.com/search?q=",
        }
        
        page = await self._get_page()
        current_url = page.url.lower()
        
        # Context-aware search: If on a specific site, use its internal search
        if "youtube.com" in current_url and engine == "google":
            engine = "youtube"
        elif "wikipedia.org" in current_url and engine == "google":
            engine = "wikipedia"
        elif "github.com" in current_url and engine == "google":
            engine = "github"

        base = _engines.get(engine.lower(), _engines["google"])
        return await self.go_to(base + query.replace(" ", "+"))

    async def click(self, selector: str = None, text: str = None) -> str:
        page = await self._get_page()
        try:
            loc = None
            if text:
                loc = page.get_by_text(text, exact=False).first
            elif selector:
                loc = page.locator(selector).first

            if loc:
                # Get bounding box for human-like movement
                box = await loc.bounding_box()
                if box:
                    # Target center of element
                    tx = box["x"] + box["width"] / 2
                    ty = box["y"] + box["height"] / 2
                    await self._move_mouse_bezier(tx, ty)
                    await loc.click(timeout=8_000, force=True)
                else:
                    await loc.click(timeout=8_000)
                return f"Clicked: '{text or selector}'"
            return "No selector or text provided."
        except PlaywrightTimeout:
            return "Element not found (timeout)."
        except Exception as e:
            return f"Click error: {e}"

    async def type_text(self, selector: str = None, text: str = "",
                        clear_first: bool = True) -> str:
        page = await self._get_page()
        try:
            el = page.locator(selector).first if selector else page.locator(":focus")
            if clear_first:
                await el.clear()
            await el.type(text, delay=50)
            return "Text typed."
        except Exception as e:
            return f"Type error: {e}"

    async def scroll(self, direction: str = "down", amount: int = 500) -> str:
        page = await self._get_page()
        try:
            y = amount if direction == "down" else -amount
            await page.mouse.wheel(0, y)
            return f"Scrolled {direction}."
        except Exception as e:
            return f"Scroll error: {e}"

    async def press(self, key: str) -> str:
        page = await self._get_page()
        try:
            await page.keyboard.press(key)
            return f"Pressed: {key}"
        except Exception as e:
            return f"Key error: {e}"

    async def get_text(self) -> str:
        page = await self._get_page()
        try:
            text = await page.inner_text("body")
            return text[:4_000]
        except Exception as e:
            return f"Could not get page text: {e}"

    async def get_url(self) -> str:
        page = await self._get_page()
        return page.url

    async def fill_form(self, fields: dict) -> str:
        page    = await self._get_page()
        results = []
        for selector, value in fields.items():
            try:
                el = page.locator(selector).first
                await el.clear()
                await el.type(str(value), delay=40)
                results.append(f"✓ {selector}")
            except Exception as e:
                results.append(f"✗ {selector}: {e}")
        return "Form filled: " + ", ".join(results)

    async def smart_click(self, description: str) -> str:
        """Grounded Smart Click: Uses AI to find exact element in AXTree/DOM before clicking."""
        page = await self._get_page()
        
        try:
            # 1. Gather semantic data
            ax_tree = await self.get_ax_tree()
            comp_dom = await self.get_compressed_dom()
            
            # 2. Use fast LLM grounding (Local import to avoid circular dependency)
            from core.llm_helper import generate_content_with_waterfall
            prompt = (
                f"Accessibility Tree:\n{ax_tree[:1500]}\n\n"
                f"Compressed DOM:\n{comp_dom[:1500]}\n\n"
                f"User wants to click: '{description}'\n"
                "INSTRUCTION: Find the best matching element. Return ONLY the exact text, aria-label, or id. "
                "CRITICAL: Do NOT explain your reasoning. Do NOT return multiple lines. If you see reasoning in your head, IGNORE IT. "
                "Output ONLY the string. Example: 'Submit' or 'login-btn'."
            )
            response = generate_content_with_waterfall(prompt)
            # Sanitize: Take only the first line and remove punctuation that breaks CSS
            precise_target = response.text.strip().split("\n")[0].strip().strip("'").strip('"')
            
            # If the LLM returned a whole paragraph anyway, it's garbage. Truncate it.
            if len(precise_target) > 50:
                precise_target = description

            # 3. Attempt precise click
            for loc in [
                page.get_by_role("button", name=precise_target).first,
                page.get_by_role("link", name=precise_target).first,
                page.get_by_text(precise_target, exact=True).first,
            ]:
                try:
                    if loc and await loc.count() > 0:
                        box = await loc.bounding_box()
                        if box:
                            await self._move_mouse_bezier(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                        await loc.click(timeout=4_000, force=True)
                        return f"Grounded click: '{precise_target}'"
                except Exception:
                    continue

            # ID Search (Separate to avoid BADSTRING css errors)
            if precise_target and len(precise_target) < 30 and " " not in precise_target:
                try:
                    loc = page.locator(f"#{precise_target}").first
                    if await loc.count() > 0:
                        await loc.click(timeout=3_000)
                        return f"Grounded ID click: '{precise_target}'"
                except Exception:
                    pass

        except Exception as e:
            print(f"[Browser] Grounding failed: {e}")

        # 4. Fallback to Deep Search (JavaScript injection)
        deep_search_js = """
        (label) => {
            const findDeep = (root) => {
                const selectors = [`[aria-label*="${label}" i]`, `[title*="${label}" i]`, 'button', 'a'];
                for (const selector of selectors) {
                    const elements = root.querySelectorAll(selector);
                    for (const el of elements) {
                        if (el.innerText?.toLowerCase().includes(label.toLowerCase()) || 
                            el.getAttribute('aria-label')?.toLowerCase().includes(label.toLowerCase())) return el;
                    }
                }
                const walkers = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
                let node;
                while (node = walkers.nextNode()) {
                    if (node.shadowRoot) {
                        const found = findDeep(node.shadowRoot);
                        if (found) return found;
                    }
                }
                return null;
            };
            const el = findDeep(document.body);
            if (el) {
                const rect = el.getBoundingClientRect();
                return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
            }
            return null;
        }
        """
        try:
            coords = await page.evaluate(deep_search_js, description)
            if coords:
                await self._move_mouse_bezier(coords["x"], coords["y"])
                await page.mouse.click(coords["x"], coords["y"])
                return f"Deep clicked: '{description}'"
        except Exception:
            pass
        return f"Could not find element: '{description}'"

    async def get_compressed_dom(self) -> str:
        """Returns a highly compressed list of interactive elements for fast reasoning."""
        page = await self._get_page()
        compress_js = """
        () => {
            const interactive = [];
            const walk = (root) => {
                if (!root) return;
                const elements = root.querySelectorAll('button, a, input, select, textarea, [role="button"], [role="link"]');
                elements.forEach(el => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        interactive.push({
                            tag: el.tagName ? el.tagName.toLowerCase() : 'unknown',
                            text: (el.innerText || el.value || "").slice(0, 30).trim(),
                            aria: el.getAttribute('aria-label') || "",
                            id: el.id || "",
                            type: el.type || ""
                        });
                    }
                });
                
                const all = root.querySelectorAll('*');
                all.forEach(el => {
                    if (el && el.shadowRoot) walk(el.shadowRoot);
                });
            };
            walk(document.body);
            return interactive.slice(0, 50); 
        }
        """
        try:
            elements = await page.evaluate(compress_js)
            lines = []
            for el in elements:
                line = f"<{el['tag']}"
                if el['id']: line += f" id='{el['id']}'"
                if el['text']: line += f" text='{el['text']}'"
                if el['aria']: line += f" aria='{el['aria']}'"
                line += ">"
                lines.append(line)
            return "\n".join(lines)
        except Exception as e:
            return f"DOM compression error: {e}"

    async def smart_type(self, description: str, text: str) -> str:
        page = await self._get_page()
        candidates = [
            ("placeholder", page.get_by_placeholder(description, exact=False)),
            ("label",       page.get_by_label(description, exact=False)),
            ("role",        page.get_by_role("textbox", name=description)),
            ("searchbox",   page.get_by_role("searchbox")),
            ("combobox",    page.get_by_role("combobox", name=description)),
        ]
        for method, loc in candidates:
            try:
                el = loc.first
                if await el.count() == 0:
                    continue
                await el.clear()
                await el.type(text, delay=50)
                return f"Typed into ({method}): '{description}'"
            except Exception:
                continue
        return f"Could not find input: '{description}'"

    async def new_tab(self, url: str = "") -> str:
        page = await self._get_page()
        ctx  = page.context
        new  = await ctx.new_page()
        self._page = new
        if url:
            return await self.go_to(url)
        return "New tab opened."

    async def close_tab(self) -> str:
        page = self._page
        if page and not page.is_closed():
            ctx   = page.context
            await page.close()
            pages = ctx.pages
            self._page = pages[-1] if pages else None
            return "Tab closed."
        return "No active tab to close."

    async def screenshot(self, path: str = None) -> str:
        page = await self._get_page()
        try:
            save_path = path or str(Path.home() / "Desktop" / "jarvis_screenshot.png")
            await page.screenshot(path=save_path, full_page=False)
            return f"Screenshot saved: {save_path}"
        except Exception as e:
            return f"Screenshot error: {e}"

    async def get_ax_tree(self) -> str:
        """Returns a simplified version of the Accessibility Tree for semantic reasoning."""
        page = await self._get_page()
        try:
            if not hasattr(page, "accessibility"):
                return "Accessibility API not supported by this browser/version."
            snapshot = await page.accessibility.snapshot()
            if not snapshot:
                return "Accessibility tree unavailable."

            def parse_node(node, depth=0):
                role = node.get("role", "unknown")
                name = node.get("name", "")
                val  = node.get("value", "")
                desc = f"{'  '*depth}[{role}]"
                if name: desc += f" '{name}'"
                if val:  desc += f" (value: {val})"
                
                results = [desc]
                for child in node.get("children", []):
                    results.append(parse_node(child, depth + 1))
                return "\n".join(results)

            return parse_node(snapshot)
        except Exception as e:
            return f"AXTree error: {e}"

    async def _move_mouse_bezier(self, target_x: float, target_y: float):
        """Moves the mouse using a quadratic Bezier curve to simulate human movement."""
        import random
        page = await self._get_page()
        try:
            # We assume a starting point since current mouse position isn't tracked easily
            start_x, start_y = target_x + 200, target_y + 200
            
            cp_x = (start_x + target_x) / 2 + (random.random() - 0.5) * 150
            cp_y = (start_y + target_y) / 2 + (random.random() - 0.5) * 150
            
            steps = 12
            for i in range(steps + 1):
                t = i / steps
                x = (1-t)**2 * start_x + 2*(1-t)*t * cp_x + t**2 * target_x
                y = (1-t)**2 * start_y + 2*(1-t)*t * cp_y + t**2 * target_y
                await page.mouse.move(x, y)
                await asyncio.sleep(0.005)
        except Exception:
            await page.mouse.move(target_x, target_y)

    async def back(self) -> str:
        page = await self._get_page()
        try:
            await page.go_back(timeout=10_000)
            return f"Navigated back: {page.url}"
        except Exception as e:
            return f"Back error: {e}"

    async def forward(self) -> str:
        page = await self._get_page()
        try:
            await page.go_forward(timeout=10_000)
            return f"Navigated forward: {page.url}"
        except Exception as e:
            return f"Forward error: {e}"

    async def reload(self) -> str:
        page = await self._get_page()
        try:
            await page.reload(timeout=15_000)
            return f"Page reloaded: {page.url}"
        except Exception as e:
            return f"Reload error: {e}"

    async def close_browser(self) -> str:
        await self._async_close()
        return f"{self.browser_name} closed."

class _SessionRegistry:
    """Tüm aktif tarayıcı oturumlarını yönetir."""

    def __init__(self):
        self._sessions:       dict[str, _BrowserSession] = {}
        self._active_browser: str                        = ""
        self._lock            = threading.Lock()

    def _get_or_create(self, browser_name: str) -> _BrowserSession:
        with self._lock:
            if browser_name not in self._sessions:
                sess = _BrowserSession(browser_name)
                sess.start()
                self._sessions[browser_name] = sess
                print(f"[Registry] New session: {browser_name}")
            return self._sessions[browser_name]

    def get(self, browser_name: str | None = None) -> _BrowserSession:
        if not browser_name:
            browser_name = self._active_browser or _detect_default_browser()
        browser_name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
        sess = self._get_or_create(browser_name)
        self._active_browser = browser_name
        return sess

    def switch(self, browser_name: str) -> str:
        browser_name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
        self._get_or_create(browser_name)
        self._active_browser = browser_name
        return f"Active browser → {browser_name}"

    def close_one(self, browser_name: str) -> str:
        with self._lock:
            sess = self._sessions.pop(browser_name, None)
        if sess:
            sess.close()
            if self._active_browser == browser_name:
                self._active_browser = ""
            return f"{browser_name} closed."
        return f"No active session for: {browser_name}"

    def close_all(self) -> str:
        with self._lock:
            names    = list(self._sessions.keys())
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self._active_browser = ""
        for s in sessions:
            try:
                s.close()
            except Exception:
                pass
        return "All browsers closed: " + (", ".join(names) if names else "none")

    def list_sessions(self) -> str:
        with self._lock:
            if not self._sessions:
                return "No active browser sessions."
            lines = []
            for name in self._sessions:
                marker = " ◀ active" if name == self._active_browser else ""
                lines.append(f"  • {name}{marker}")
            return "Open browsers:\n" + "\n".join(lines)


_registry = _SessionRegistry()

def browser_control(
    parameters:    dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params  = parameters or {}
    action  = params.get("action", "").lower().strip()
    browser = params.get("browser", "").lower().strip() or None
    result  = "Unknown action."

    if action == "switch":
        target = browser or params.get("target", "").lower().strip()
        result = _registry.switch(target) if target else "Please specify a browser."
        _log(player, result)
        return result

    if action == "list_browsers":
        result = _registry.list_sessions()
        _log(player, result)
        return result

    if action == "close_all":
        result = _registry.close_all()
        _log(player, result)
        return result

    try:
        sess = _registry.get(browser)
    except Exception as e:
        result = f"Could not start browser session: {e}"
        _log(player, result)
        return result

    try:
        if action == "go_to":
            result = sess.run(sess.go_to(params.get("url", "")))
        elif action == "search":
            result = sess.run(sess.search(params.get("query", ""), params.get("engine", "google")))
        elif action == "click":
            result = sess.run(sess.click(params.get("selector"), params.get("text")))
        elif action == "type":
            result = sess.run(sess.type_text(
                params.get("selector"), params.get("text", ""), params.get("clear_first", True)))
        elif action == "scroll":
            result = sess.run(sess.scroll(params.get("direction", "down"), int(params.get("amount", 500))))
        elif action == "fill_form":
            result = sess.run(sess.fill_form(params.get("fields", {})))
        elif action == "smart_click":
            result = sess.run(sess.smart_click(params.get("description", "")))
        elif action == "smart_type":
            result = sess.run(sess.smart_type(params.get("description", ""), params.get("text", "")))
        elif action == "get_text":
            result = sess.run(sess.get_text())
        elif action == "get_ax_tree":
            result = sess.run(sess.get_ax_tree())
        elif action == "get_compressed_dom":
            result = sess.run(sess.get_compressed_dom())
        elif action == "get_url":
            result = sess.run(sess.get_url())
        elif action == "press":
            result = sess.run(sess.press(params.get("key", "Enter")))
        elif action == "new_tab":
            result = sess.run(sess.new_tab(params.get("url", "")))
        elif action == "close_tab":
            result = sess.run(sess.close_tab())
        elif action == "screenshot":
            result = sess.run(sess.screenshot(params.get("path")))
        elif action == "back":
            result = sess.run(sess.back())
        elif action == "forward":
            result = sess.run(sess.forward())
        elif action == "reload":
            result = sess.run(sess.reload())
        elif action == "close":
            target = browser or _registry._active_browser
            result = _registry.close_one(target) if target else "No browser specified."
        else:
            result = f"Unknown browser action: '{action}'"

    except concurrent.futures.TimeoutError:
        result = f"Browser action '{action}' timed out (60s)."
    except Exception as e:
        result = f"Browser error ({action}): {e}"

    _log(player, result)
    return result


def _log(player, text: str):
    short = str(text)[:80]
    print(f'[Browser] {short}')
    if player:
        player.write_log(f'[browser] {short[:60]}')
