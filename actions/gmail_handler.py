
import asyncio
import concurrent.futures
from pathlib import Path
from actions.browser_control import _registry, _log
from memory.account_manager import get_account

async def _gmail_draft(page, to, subject, body):
    """Visible Gmail drafting logic."""
    await page.goto("https://mail.google.com/mail/u/0/#inbox", wait_until="domcontentloaded")
    
    # Click 'Compose'
    try:
        await page.get_by_role("button", name="Compose").click(timeout=10000)
    except:
        # Fallback for different UI versions
        await page.get_by_text("Compose").first.click(timeout=10000)
        
    await asyncio.sleep(1)
    
    # Fill 'To'
    if to:
        await page.get_by_role("combobox", name="To").type(to, delay=50)
        await page.keyboard.press("Enter")
    
    # Fill 'Subject'
    if subject:
        await page.get_by_placeholder("Subject").type(subject, delay=50)
        
    # Fill 'Body'
    if body:
        await page.get_by_role("textbox", name="Message Body").type(body, delay=30)
        
    return "Draft prepared. JARVIS is now pausing for your review. You can verify and hit send, or tell me to send it."

async def _gmail_search(page, query):
    await page.goto(f"https://mail.google.com/mail/u/0/#search/{query.replace(' ', '+')}", wait_until="domcontentloaded")
    await asyncio.sleep(2)
    return f"Searched Gmail for: {query}. Showing results in browser."

def gmail_processor(parameters: dict = None, player=None, **kwargs) -> str:
    params = parameters or {}
    action = params.get("action", "search").lower()
    alias  = params.get("account_alias", "default")
    
    # In the future, we can use 'alias' to select specific profiles via AccountManager
    # For now, we use the active browser session
    try:
        sess = _registry.get("chrome") # Default to chrome for Gmail
    except Exception as e:
        return f"Could not start browser: {e}"
        
    try:
        if action == "draft":
            res = sess.run(_gmail_draft(
                sess._page, 
                params.get("to"), 
                params.get("subject"), 
                params.get("body")
            ))
        elif action == "search":
            res = sess.run(_gmail_search(sess._page, params.get("query", "")))
        elif action == "send":
            # Explicit override to click send
            async def _click_send(p):
                await p.get_by_text("Send").first.click()
                return "Email sent."
            res = sess.run(_click_send(sess._page))
        else:
            res = f"Unknown Gmail action: {action}"
            
        _log(player, res)
        return res
    except Exception as e:
        return f"Gmail error: {e}"
