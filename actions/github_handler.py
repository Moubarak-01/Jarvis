
import asyncio
from actions.browser_control import _registry, _log

async def _github_search(page, query):
    await page.goto(f"https://github.com/search?q={query.replace(' ', '+')}", wait_until="domcontentloaded")
    return f"Searched GitHub for: {query}"

async def _github_create_issue(page, repo, title, body):
    await page.goto(f"https://github.com/{repo}/issues/new", wait_until="domcontentloaded")
    await page.get_by_placeholder("Title").type(title, delay=50)
    await page.get_by_placeholder("Leave a comment").type(body, delay=30)
    return "GitHub Issue drafted. You can review and click 'Submit new issue'."

def github_processor(parameters: dict = None, player=None, **kwargs) -> str:
    params = parameters or {}
    action = params.get("action", "search").lower()
    
    try:
        sess = _registry.get("chrome")
    except Exception as e:
        return f"Could not start browser: {e}"
        
    try:
        if action == "search":
            res = sess.run(_github_search(sess._page, params.get("query", "")))
        elif action == "draft_issue":
            res = sess.run(_github_create_issue(
                sess._page, 
                params.get("repo"), 
                params.get("title"), 
                params.get("body")
            ))
        else:
            res = f"Unknown GitHub action: {action}"
            
        _log(player, res)
        return res
    except Exception as e:
        return f"GitHub error: {e}"
