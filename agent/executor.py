import json
import re
import sys
import time
import threading
import subprocess
import tempfile
import os
from pathlib import Path
from typing import Callable

from agent.planner       import create_plan, replan
from agent.error_handler import analyze_error, generate_fix, ErrorDecision


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

from core.llm_helper import generate_content_with_waterfall


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


# _get_api_key removed in favor of llm_helper

def _run_generated_code(description: str, speak: Callable | None = None) -> str:


    if speak:
        speak("Writing custom code for this task, sir.")

    home      = Path.home()
    desktop   = home / "Desktop"
    downloads = home / "Downloads"
    documents = home / "Documents"

    if not desktop.exists():
        try:
            import winreg
            key     = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
            desktop = Path(winreg.QueryValueEx(key, "Desktop")[0])
        except Exception:
            pass

    try:
        sys_inst = (
            "You are an expert Python developer. "
            "Write clean, complete, working Python code. "
            "Use standard library + common packages. "
            "Install missing packages with subprocess + pip if needed. "
            "Return ONLY the Python code. No explanation, no markdown, no backticks.\n\n"
            f"SYSTEM PATHS:\n"
            f"  Desktop   = r'{desktop}'\n"
            f"  Downloads = r'{downloads}'\n"
            f"  Documents = r'{documents}'\n"
            f"  Home      = r'{home}'\n"
        )
        response = generate_content_with_waterfall(
            f"Write Python code to accomplish this task:\n\n{description}",
            system_instruction=sys_inst
        )
        code = response.text.strip()
        code = re.sub(r"```(?:python)?", "", code).strip().rstrip("`").strip()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        print(f"[Executor] 🐍 Running generated code: {tmp_path}")

        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True,
            timeout=120, cwd=str(Path.home())
        )

        try:
            os.unlink(tmp_path)
        except Exception:
            pass

        output = result.stdout.strip()
        error  = result.stderr.strip()

        if result.returncode == 0 and output:
            return output
        elif result.returncode == 0:
            return "Task completed successfully."
        elif error:
            raise RuntimeError(f"Code error: {error[:400]}")
        return "Completed."

    except subprocess.TimeoutExpired:
        raise RuntimeError("Generated code timed out after 120 seconds.")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Generated code failed: {e}")

def _inject_context(params: dict, tool: str, step_results: dict, goal: str = "") -> dict:
    if not step_results:
        return params

    params = dict(params)

    if tool == "file_controller" and params.get("action") in ("write", "create_file"):
        content = params.get("content", "")
        if not content or len(content) < 50:
            all_results = [
                v for v in step_results.values()
                if v and len(v) > 100 and v not in ("Done.", "Completed.")
            ]
            if all_results:
                combined = "\n\n---\n\n".join(all_results)
                translated = _translate_to_goal_language(combined, goal)
                params["content"] = translated
                print(f"[Executor] 💉 Injected + translated content")

    return params
def _detect_language(text: str) -> str:
    try:
        response = generate_content_with_waterfall(
            f"What language is this text written in? "
            f"Reply with ONLY the language name in English (e.g. Turkish, English, French).\n\n"
            f"Text: {text[:200]}"
        )
        return response.text.strip()
    except Exception:
        return "English"


def _translate_to_goal_language(content: str, goal: str) -> str:
    if not goal:
        return content
    try:
        target_lang = _detect_language(goal)
        print(f"[Executor] 🌐 Translating to: {target_lang}")

        prompt = (
            f"You are a professional translator. "
            f"Translate the following text into {target_lang}.\n"
            f"IMPORTANT:\n"
            f"- Translate EVERYTHING, leave nothing in English\n"
            f"- Keep all facts, numbers, and data intact\n"
            f"- Keep the structure and formatting\n"
            f"- Output ONLY the translated text, nothing else\n\n"
            f"Text to translate:\n{content[:4000]}"
        )
        response = generate_content_with_waterfall(prompt)
        translated = response.text.strip()
        print(f"[Executor] ✅ Translation done ({target_lang})")
        return translated
    except Exception as e:
        print(f"[Executor] ⚠️ Translation failed: {e}")
        return content

def _call_tool(tool: str, parameters: dict, speak: Callable | None) -> str:

    if tool == "open_app":
        from actions.open_app import open_app
        return open_app(parameters=parameters, player=None) or "Done."

    elif tool == "web_search":
        from actions.web_search import web_search
        return web_search(parameters=parameters, player=None) or "Done."
    elif tool == "game_updater":
        from actions.game_updater import game_updater
        return game_updater(parameters=parameters, player=None, speak=speak) or "Done."
    elif tool == "browser_control":
        from actions.browser_control import browser_control
        return browser_control(parameters=parameters, player=None) or "Done."

    elif tool == "file_controller":
        from actions.file_controller import file_controller
        return file_controller(parameters=parameters, player=None) or "Done."

    elif tool == "code_helper":
        from actions.code_helper import code_helper
        return code_helper(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "dev_agent":
        from actions.dev_agent import dev_agent
        return dev_agent(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "screen_process":
        from actions.screen_processor import screen_process
        screen_process(parameters=parameters, player=None)
        return "Screen captured and analyzed."

    elif tool == "send_message":
        from actions.send_message import send_message
        return send_message(parameters=parameters, player=None) or "Done."

    elif tool == "reminder":
        from actions.reminder import reminder
        return reminder(parameters=parameters, player=None) or "Done."

    elif tool == "youtube_video":
        from actions.youtube_video import youtube_video
        return youtube_video(parameters=parameters, player=None) or "Done."

    elif tool == "weather_report":
        from actions.weather_report import weather_action
        return weather_action(parameters=parameters, player=None) or "Done."

    elif tool == "computer_settings":
        from actions.computer_settings import computer_settings
        return computer_settings(parameters=parameters, player=None) or "Done."

    elif tool == "desktop_control":
        from actions.desktop import desktop_control
        return desktop_control(parameters=parameters, player=None) or "Done."

    elif tool == "computer_control":
        from actions.computer_control import computer_control
        return computer_control(parameters=parameters, player=None) or "Done."

    elif tool == "generated_code":
        description = parameters.get("description", "")
        if not description:
            raise ValueError("generated_code requires a 'description' parameter.")
        return _run_generated_code(description, speak=speak)

    elif tool == "flight_finder":
        from actions.flight_finder import flight_finder
        return flight_finder(parameters=parameters, player=None, speak=speak) or "Done."

    else:
        print(f"[Executor] ⚠️ Unknown tool '{tool}' — falling back to generated_code")
        return _run_generated_code(f"Accomplish this task: {parameters}", speak=speak)

class AgentExecutor:

    MAX_REPLAN_ATTEMPTS = 2
    MAX_REACTIVE_STEPS  = 15

    def execute(
        self,
        goal:        str,
        speak:       Callable | None        = None,
        cancel_flag: threading.Event | None = None,
    ) -> str:
        print(f"\n[Executor] 🎯 Goal: {goal}")
        
        # Decide if we use Reactive Mode (Browser/Desktop tasks)
        reactive_keywords = (
            "browser", "chrome", "edge", "website", "click", "type", "screen",
            "youtube", "google", "search", "open", "go to", "find", "check", 
            "look", "scroll", "press", "button", "link", "page"
        )
        is_reactive = any(kw in goal.lower() for kw in reactive_keywords)
        
        if is_reactive:
            print("[Executor] 🔄 Entering Reactive Mode (Look-Plan-Act)")
            return self._execute_reactive(goal, speak, cancel_flag)
        
        return self._execute_sequential(goal, speak, cancel_flag)

    def _execute_reactive(self, goal: str, speak: Callable | None, cancel_flag: threading.Event | None) -> str:
        completed_steps = []
        step_results    = {}
        
        for i in range(1, self.MAX_REACTIVE_STEPS + 1):
            if cancel_flag and cancel_flag.is_set():
                return "Task cancelled."

            # 1. LOOK: Get AXTree, Compressed DOM, and Screenshot in parallel
            from actions.browser_control import browser_control
            from actions.screen_processor import _capture_screen
            from concurrent.futures import ThreadPoolExecutor

            print(f"\n[Executor] 👁️ Step {i}: Observing state (Parallel)...")
            with ThreadPoolExecutor(max_workers=3) as pool:
                f_ax   = pool.submit(browser_control, {"action": "get_ax_tree"})
                f_dom  = pool.submit(browser_control, {"action": "get_compressed_dom"})
                f_shot = pool.submit(_capture_screen)
                
                ax_tree   = f_ax.result()
                comp_dom  = f_dom.result()
                shot_data = f_shot.result()
                shot, mime = shot_data if shot_data else (None, None)
            
            # 2. PLAN: Ask LLM for the SINGLE next step
            state_context = (
                f"Goal: {goal}\n\n"
                f"Accessibility Tree:\n{str(ax_tree)[:2000]}\n\n"
                f"Compressed DOM (Interactive Elements):\n{str(comp_dom)[:2000]}\n\n"
                "Previous Steps:\n"
            )
            for s in completed_steps:
                state_context += f"- {s.get('description')}: {s.get('result')}\n"
            
            prompt = (
                f"{state_context}\n\n"
                "Based on the goal and current screen state, what is the ONE next tool action to take?\n"
                "Return ONLY valid JSON in this exact format:\n"
                "{\n"
                '  "tool": "name_of_tool",\n'
                '  "parameters": {"param1": "value1"},\n'
                '  "description": "Short explanation of this step"\n'
                "}\n\n"
                "Available Tools: browser_control, web_search, computer_control, screen_process.\n"
                "If the goal is fully reached, return: {'status': 'complete', 'summary': '...'}"
            )
            
            try:
                from agent.planner import PLANNER_PROMPT
                import PIL.Image
                import io
                
                img = PIL.Image.open(io.BytesIO(shot))
                response = generate_content_with_waterfall(
                    [prompt, img], 
                    system_instruction=PLANNER_PROMPT,
                    is_vision=True
                )
                
                text = response.text.strip()
                # Enhanced JSON cleaning: Find the first { and last }
                json_match = re.search(r"\{.*\}", text, re.DOTALL)
                if json_match:
                    text = json_match.group(0)
                
                decision = json.loads(text)
                
                if decision.get("status") == "complete":
                    return decision.get("summary", "Goal achieved.")
                
                tool   = decision.get("tool")
                if not tool:
                    print("[Executor] ⚠️ AI returned JSON without a 'tool' key. Retrying...")
                    continue

                params = decision.get("parameters", {})
                desc   = decision.get("description", "Executing next step")
                
                # Clean up params that might have hallucinated formatting
                if isinstance(params, str):
                    try:
                        params = json.loads(params.replace("'", '"'))
                    except:
                        pass
                
                print(f"[Executor] ▶️ Reactive Action: [{tool}] {desc}")
                
                # 3. ACT: Execute the step
                result = _call_tool(tool, params, speak)
                
                # 4. RECORD: Save for next loop
                decision["result"] = result
                completed_steps.append(decision)
                step_results[i] = result
                
            except Exception as e:
                print(f"[Executor] ❌ Reactive step failed: {e}")
                # Fallback to a quick sequential plan if reactive loop gets stuck
                return self._execute_sequential(goal, speak, cancel_flag)

        return "Reached max reactive steps."

    def _execute_sequential(
        self,
        goal:        str,
        speak:       Callable | None        = None,
        cancel_flag: threading.Event | None = None,
    ) -> str:
        replan_attempts = 0
        completed_steps = []
        step_results    = {} 
        plan            = create_plan(goal)

        while True:
            steps = plan.get("steps", [])
            if not steps:
                return "I couldn't create a valid plan, sir."

            success      = True
            failed_step  = None
            failed_error = ""

            for step in steps:
                if cancel_flag and cancel_flag.is_set():
                    return "Task cancelled."

                step_num = step.get("step", "?")
                tool     = step.get("tool", "generated_code")
                desc     = step.get("description", "")
                params   = step.get("parameters", {})

                params = _inject_context(params, tool, step_results, goal=goal)
                print(f"\n[Executor] ▶️ Step {step_num}: [{tool}] {desc}")

                attempt = 1
                step_ok = False

                while attempt <= 3:
                    try:
                        result = _call_tool(tool, params, speak)
                        step_results[step_num] = result 
                        completed_steps.append(step)
                        step_ok = True
                        break
                    except Exception as e:
                        error_msg = str(e)
                        recovery = analyze_error(step, error_msg, attempt=attempt)
                        if recovery["decision"] == ErrorDecision.RETRY:
                            attempt += 1; time.sleep(2); continue
                        elif recovery["decision"] == ErrorDecision.SKIP:
                            completed_steps.append(step); step_ok = True; break
                        elif recovery["decision"] == ErrorDecision.ABORT:
                            return f"Task aborted: {recovery.get('reason', '')}"
                        
                        failed_step  = step
                        failed_error = error_msg
                        success      = False
                        break

                if not success: break

            if success:
                return self._summarize(goal, completed_steps, speak)

            if replan_attempts >= self.MAX_REPLAN_ATTEMPTS:
                return "Task failed after multiple attempts."

            replan_attempts += 1
            plan = replan(goal, completed_steps, failed_step, failed_error)

    def _summarize(self, goal: str, completed_steps: list, speak: Callable | None) -> str:
        fallback = f"All done, sir. Completed {len(completed_steps)} steps for: {goal[:60]}."
        try:
            steps_str = "\n".join(f"- {s.get('description', '')}" for s in completed_steps)
            prompt    = (
                f'User goal: "{goal}"\n'
                f"Completed steps:\n{steps_str}\n\n"
                "Write a single natural sentence summarizing what was accomplished. "
                "Address the user as 'sir'. Be direct and positive."
            )
            response = generate_content_with_waterfall(prompt)
            summary  = response.text.strip()
            if speak: speak(summary)
            return summary
        except Exception:
            if speak: speak(fallback)
            return fallback