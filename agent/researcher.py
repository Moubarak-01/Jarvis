import time
import json
from core.llm_helper import generate_content_with_waterfall

class DeepResearchAgent:
    def __init__(self, speak_callable=None):
        self.speak = speak_callable

    def run(self, goal: str, deadline_minutes: float = None, cancel_flag=None) -> str:
        """
        Executes an autonomous research loop.
        """
        if self.speak:
            self.speak("Initiating deep research protocols.")
            
        start_time = time.time()
        
        # Determine depth based on deadline
        if deadline_minutes is None:
            max_articles = 3
            depth_level = "standard"
            time_limit_seconds = 180  # Default 3 mins if no deadline
        else:
            depth_level = "deep" if deadline_minutes > 5 else "quick"
            max_articles = 5 if depth_level == "deep" else 3
            time_limit_seconds = deadline_minutes * 60
            
        print(f"[Researcher] Goal: {goal}")
        print(f"[Researcher] Mode: {depth_level}, Max Articles: {max_articles}")
        
        # 1. Generate Search Queries
        query_prompt = f"""
        Goal: {goal}
        You are a Deep Research Agent. 
        Generate exactly 3 specific Google search queries to help research this goal.
        Return ONLY a JSON list of strings, nothing else. Example: ["query 1", "query 2", "query 3"]
        """
        try:
            response = generate_content_with_waterfall(query_prompt)
            # Find the JSON array
            text = response.text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            queries = json.loads(text)
            if not isinstance(queries, list):
                queries = [goal]
        except Exception as e:
            print(f"[Researcher] Failed to parse queries: {e}")
            queries = [goal]
            
        from actions.browser_control import browser_control
        
        gathered_text = ""
        articles_read = 0
        
        for q in queries[:2]:  # Use up to 2 queries to save time
            if cancel_flag and cancel_flag.is_set():
                return "Research cancelled."
                
            if (time.time() - start_time) > time_limit_seconds:
                print("[Researcher] Time limit reached.")
                break
                
            print(f"[Researcher] Searching: {q}")
            browser_control({"action": "search", "query": q})
            time.sleep(2)
            
            # Use smart click to try to open the first link.
            # Google search results usually have heading level 3 for titles
            try:
                # We can inject JS or use the text. Let's just grab the text of the search results for quick info.
                search_text = browser_control({"action": "get_text"})
                gathered_text += f"\n--- Search Results for '{q}' ---\n"
                gathered_text += search_text[:1500]
                articles_read += 1
            except Exception as e:
                print(f"[Researcher] Error getting search results: {e}")
                
            if articles_read >= max_articles:
                break
                
        # Close the browser safely
        browser_control({"action": "close"})

        if self.speak:
            self.speak("Synthesizing research findings.")
            
        # 2. Synthesize
        synth_prompt = f"""
        Goal: {goal}
        
        Information gathered:
        {gathered_text}
        
        Synthesize a comprehensive report answering the goal. Do not mention that you cannot browse or interact.
        Provide a well-structured summary.
        """
        synth_resp = generate_content_with_waterfall(synth_prompt)
        final_report = synth_resp.text
        
        if self.speak:
            self.speak("Research complete. The report is ready.")
            
        return final_report

def deep_research_action(parameters: dict, player=None, speak=None) -> str:
    goal = parameters.get("goal", "Research topic")
    deadline = parameters.get("deadline_minutes", None)
    
    agent = DeepResearchAgent(speak_callable=speak)
    # The Executor handles cancel flags, but for a direct action, we might not have it.
    # Executor _call_tool doesn't pass cancel_flag.
    return agent.run(goal=goal, deadline_minutes=deadline)
