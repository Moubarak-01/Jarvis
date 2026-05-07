
import asyncio
from actions.browser_control import _registry, _log

async def _outlook_draft(page, to, subject, body):
    """Visible Outlook drafting logic."""
    await page.goto("https://outlook.live.com/mail/0/", wait_until="domcontentloaded")
    await asyncio.sleep(2)
    
    # Click 'New mail'
    try:
        await page.get_by_role("button", name="New mail").click(timeout=10000)
    except:
        await page.get_by_text("New mail").first.click(timeout=10000)
        
    await asyncio.sleep(1)
    
    # Fill 'To'
    if to:
        # Outlook 'To' field can be tricky, often a div or specific aria-label
        await page.get_by_label("To").type(to, delay=50)
        await page.keyboard.press("Enter")
    
    # Fill 'Subject'
    if subject:
        await page.get_by_placeholder("Add a subject").type(subject, delay=50)
        
    # Fill 'Body'
    if body:
        # Outlook body is often a contenteditable div
        await page.get_by_label("Message body").type(body, delay=30)
        
    return "Outlook draft prepared. JARVIS is pausing for review. Hit send when ready!"

async def _outlook_search(page, query):
    await page.goto("https://outlook.live.com/mail/0/", wait_until="domcontentloaded")
    await page.get_by_placeholder("Search").type(query, delay=50)
    await page.keyboard.press("Enter")
    return f"Searched Outlook for: {query}"

def outlook_processor(parameters: dict = None, player=None, **kwargs) -> str:
    params = parameters or {}
    action = params.get("action", "search").lower()
    
    try:
        sess = _registry.get("edge") # Default to edge for Outlook/Microsoft
    except Exception as e:
        return f"Could not start browser: {e}"
        
    try:
        if action == "draft":
            res = sess.run(_outlook_draft(
                sess._page, 
                params.get("to"), 
                params.get("subject"), 
                params.get("body")
            ))
        elif action == "search":
            res = sess.run(_outlook_search(sess._page, params.get("query", "")))
        elif action == "send":
            async def _click_send(p):
                await p.get_by_label("Send").first.click()
                return "Outlook email sent."
            res = sess.run(_click_send(sess._page))
        else:
            res = f"Unknown Outlook action: {action}"
            
        _log(player, res)
        return res
    except Exception as e:
        return f"Outlook error: {e}"
