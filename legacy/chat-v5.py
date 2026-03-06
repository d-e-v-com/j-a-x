#!/usr/bin/env python3
"""ollama-headless-chat-v5.py (v5.4-alpha)

Advanced Multi-threaded Async Terminal UI for AI-Admin.
Architecture: UI Thread, Input Thread, and Agent Worker Thread.
Features: 32k Context, True Non-blocking Queue, and Interactive Boot.
"""

import sys
import os
import json
import time
import argparse
import readline
import atexit
import threading
import queue
import re
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich.markdown import Markdown
from rich.layout import Layout
from rich.box import ROUNDED, DOUBLE
from rich.spinner import Spinner
from rich.rule import Rule
from rich.columns import Columns

# Import tools from the runner script
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from ollama_headless.ollama_headless import (
    Policy, Tooling, OllamaClient, tool_schema, boot_sequence, 
    heuristic_extract_tool_calls
)

VERSION = "v5.4.0-alpha"
MAX_CTX = 32768
console = Console()

ASCII_BANNER = r"""[bold blue]
    ___    ____      ___    ____  __  _______   _ 
   /   |  /  _/     /   |  / __ \/  |/  /  _/  / |
  / /| |  / /      / /| | / / / / /|_/ // /   /  |
 / ___ |_/ /      / ___ |/ /_/ / /  / // /   / / |
/_/  |_/___/     /_/  |_/_____/_/  /_/___/  /_/  |_|
[/][dim]      AUTONOMOUS LOCAL INTELLIGENCE UNIT[/]
"""

class ChatState:
    def __init__(self, role, model, unrestricted):
        self.role = role
        self.model = model
        self.unrestricted = unrestricted
        self.tokens_used = 0
        self.history = [] # (role, content)
        self.current_thinking = ""
        self.current_steps = []
        self.processing = False
        self.boot_complete = False
        self.boot_start_time = time.time()
        self.boot_duration = 0.0
        self.messages = []
        self.last_user_prompt = ""
        self.input_queue = queue.Queue()
        self.exit_requested = False

    def update_tokens(self, meta):
        self.tokens_used = meta.get("prompt_eval_count", 0) + meta.get("eval_count", 0)

class UIBuilder:
    @staticmethod
    def make_layout() -> Layout:
        layout = Layout()
        layout.split(
            Layout(name="header", size=8),
            Layout(name="body", ratio=1),
            Layout(name="feedback", size=1),
            Layout(name="footer", size=3)
        )
        layout["body"].split_row(
            Layout(name="history", ratio=2),
            Layout(name="logic", ratio=1)
        )
        return layout

    @staticmethod
    def render_history(state: ChatState):
        table = Table.grid(expand=True)
        for role, content in state.history[-6:]:
            if role == "user":
                table.add_row(Panel(Text(content, style="bright_white"), title="[bold magenta]USER[/]", border_style="magenta", box=ROUNDED))
            elif role == "assistant":
                table.add_row(Panel(Markdown(content), title="[bold green]ASSISTANT[/]", border_style="green", box=ROUNDED))
        
        if state.processing and state.last_user_prompt:
            table.add_row(Panel(Text(state.last_user_prompt, style="bright_white"), title="[bold magenta]PROCESSING...[/]", border_style="magenta", box=ROUNDED))
            if state.current_thinking:
                table.add_row(Panel(Text(state.current_thinking, style="grey70 on grey15"), title="[italic blue]Thinking...[/]", border_style="blue"))
        return table

    @staticmethod
    def render_logic(state: ChatState):
        table = Table.grid(expand=True)
        steps_table = Table.grid(expand=True)
        
        if not state.boot_complete:
            steps_table.add_row(Text(f"Booting Directives... {time.time() - state.boot_start_time:.1f}s", style="bold yellow"))
        else:
            steps_table.add_row(Text(f"Mission Ready. (Boot: {state.boot_duration:.1f}s)", style="bold green"))
            
        steps_table.add_row(Rule(style="dim yellow"))
        for s in state.current_steps[-25:]:
            steps_table.add_row(Text(" • ") + Text.from_markup(s))
        
        if state.processing:
            if not state.current_thinking:
                steps_table.add_row(Columns([Text(" • "), Text("Analyzing... ", style="dim"), Spinner("dots")], padding=0))
            else:
                steps_table.add_row(Columns([Text(" • "), Text("Streaming... ", style="cyan"), Spinner("bouncingBar")], padding=0))
        
        table.add_row(Panel(steps_table, title="[bold yellow]Agent Logic[/]", border_style="yellow", box=ROUNDED))
        return table

    @staticmethod
    def render_footer(state: ChatState):
        ctx_pct = (state.tokens_used / MAX_CTX) * 100
        ctx_color = "green" if ctx_pct < 70 else "yellow" if ctx_pct < 90 else "red"
        mode_str = "[bold red]UNRESTRICTED[/]" if state.unrestricted else "[bold green]RESTRICTED[/]"
        
        grid = Table.grid(expand=True)
        grid.add_column(justify="left", ratio=1)
        grid.add_column(justify="center", ratio=1)
        grid.add_column(justify="right", ratio=1)
        grid.add_row(
            Text.from_markup(f" [bold white]AI-ADMIN[/] [dim]{VERSION}[/] | [cyan]{state.role}[/]"),
            Text.from_markup(f"Mode: {mode_str} | Model: [dim]{state.model}[/]"),
            Text.from_markup(f"Context: [{ctx_color}]{ctx_pct:.1f}%[/] [dim]({state.tokens_used // 1000}k/{MAX_CTX // 1000}k)[/] ")
        )
        return Panel(grid, style="cyan on grey11", box=ROUNDED)

def setup_history():
    history_file = Path.home() / ".ollama_headless_v5_history"
    if history_file.exists():
        try: readline.read_history_file(str(history_file))
        except: pass
    readline.set_history_length(1000)
    atexit.register(readline.write_history_file, str(history_file))

def agent_worker(state, client, model, tooling):
    """Background thread for mission execution."""
    while not state.exit_requested:
        try:
            task = state.input_queue.get(timeout=0.1)
        except queue.Empty:
            continue
            
        if task is None: break
        
        kind, data = task
        state.processing = True
        
        if kind == "boot_packet":
            state.current_steps.append(f"[green][OK][/] Injecting: [dim]{data['name']}[/]")
            state.messages.append({"role": "user", "content": f"### MISSION DIRECTIVE: {data['name']}\n\n{data['content']}"})
            resp = client.chat(model=model, messages=state.messages, tools=[])
            state.messages.append(resp.get("message") or {"role": "assistant", "content": "Acknowledged."})
            state.update_tokens(resp)
            if data.get("is_final_boot"):
                state.boot_complete = True
                state.boot_duration = time.time() - state.boot_start_time
            
        elif kind == "user_prompt":
            state.last_user_prompt = data
            state.messages.append({"role": "user", "content": data})
            
            for step in range(1, 25):
                state.current_thinking = ""
                state.current_steps.append(f"Step {step}: Model call...")
                full_content = ""
                tool_calls = []
                
                for chunk in client.chat_stream(model=model, messages=state.messages, tools=tool_schema()):
                    if "error" in chunk:
                        state.current_steps.append(f"[bold red]FATAL:[/] {chunk['error']}")
                        break
                    if "message" in chunk:
                        m = chunk["message"]
                        if "content" in m:
                            full_content += m["content"]
                            state.current_thinking = full_content
                        if "tool_calls" in m:
                            tool_calls.extend(m["tool_calls"])
                    if chunk.get("done"):
                        state.update_tokens(chunk)

                assistant_msg = {"role": "assistant", "content": full_content}
                if tool_calls: assistant_msg["tool_calls"] = tool_calls
                state.messages.append(assistant_msg)

                if not tool_calls:
                    tool_calls = heuristic_extract_tool_calls(full_content)
                    if not tool_calls:
                        state.history.append(("assistant", full_content))
                        state.current_steps.append(f"[green]Turn Complete.[/]")
                        state.last_user_prompt = ""
                        break
                
                for call in tool_calls:
                    fn_info = call.get("function") or {}
                    fn_name = fn_info.get("name")
                    raw_args = fn_info.get("arguments")
                    fn_args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                    state.current_steps.append(f"Tool: [bold cyan]{fn_name}[/]")
                    try:
                        if fn_name == "list_files": out = tooling.list_files(**fn_args)
                        elif fn_name == "read_file": out = tooling.read_file(**fn_args)
                        elif fn_name == "write_file": out = tooling.write_file(**fn_args)
                        elif fn_name == "run_cmd": out = tooling.run_cmd(**fn_args)
                        elif fn_name == "grep_search": out = tooling.grep_search(**fn_args)
                        elif fn_name == "git_status": out = tooling.git_status()
                        elif fn_name == "git_diff": out = tooling.git_diff()
                        elif fn_name == "git_stash": out = tooling.git_stash()
                        elif fn_name == "git_pop": out = tooling.git_pop()
                        elif fn_name == "git_commit": out = tooling.git_commit(**fn_args)
                        elif fn_name == "git_push": out = tooling.git_push(**fn_args)
                        else: out = {"error": f"Unknown tool: {fn_name}"}
                    except Exception as e: out = {"error": str(e)}
                    res_str = str(out).replace('\n', ' ')
                    state.current_steps.append(f"Result: [dim]{res_str[:120]}...[/]")
                    state.messages.append({"role": "tool", "name": fn_name, "content": json.dumps(out)})

        state.processing = False
        state.current_thinking = ""
        state.current_steps = []
        state.input_queue.task_done()

def input_thread(state):
    """Background thread waiting for blocking user input."""
    while not state.exit_requested:
        try:
            # We use console.input but we're in a separate thread so it doesn't block UI refresh
            user_input = console.input(f"[bold magenta]prompt>[/] ").strip()
            if user_input.lower() in ["exit", "quit"]:
                state.exit_requested = True
                break
            if user_input:
                state.history.append(("user", user_input))
                state.input_queue.put(("user_prompt", user_input))
        except (EOFError, KeyboardInterrupt):
            state.exit_requested = True
            break

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--role", default="sysadmin")
    ap.add_argument("--unrestricted", action="store_true")
    args = ap.parse_args()

    repo_root = Path(args.repo).resolve()
    policy_name = "unrestricted_policy.yaml" if args.unrestricted else "policy.yaml"
    policy_path = repo_root / "scripts" / "ollama_headless" / policy_name
    audit_path = Path("/var/log/ai-admin/ollama_headless_audit.jsonl")

    policy = Policy.from_file(policy_path, repo_root, allow_unsafe_cmds=args.unrestricted)
    tooling = Tooling(policy, audit_path)
    client = OllamaClient(policy.ollama_base_url)
    model = "qwen3-coder:latest"

    state = ChatState(args.role, model, args.unrestricted)
    setup_history()
    
    # 1. Start Worker and Input threads
    worker = threading.Thread(target=agent_worker, args=(state, client, model, tooling), daemon=True)
    worker.start()
    
    in_thread = threading.Thread(target=input_thread, args=(state,), daemon=True)
    in_thread.start()

    # 2. Setup Mission Prompt
    system = (
        f"### MISSION ARCHITECTURE: AI-ADMIN AUTONOMOUS UNIT\n"
        f"IDENTITY: You are an autonomous agent operating as the '{args.role}' role in CHAT MODE.\n"
        f"CORE DIRECTIVE: Analyze provided CORE MISSION DIRECTIVES and execute using TOOLS.\n\n"
        f"### OPERATIONAL RULES:\n"
        f"1. SOURCE OF TRUTH: CORE MISSION DIRECTIVES are your foundation.\n"
        f"2. ACTION OVER CHAT: Call tools immediately.\n"
        f"Available tools: list_files, read_file, write_file, run_cmd, grep_search, git_status, git_diff, git_stash, git_pop, git_commit, git_push, request_permission."
    )
    state.messages.append({"role": "system", "content": system})

    # 3. Queue boot files
    boot_files = [
        ("README.md", repo_root / "README.md"),
        ("AGENTS.md", repo_root / "AGENTS.md"),
        (f"Role: {args.role}", repo_root / "roles" / f"{args.role}.md"),
        ("Procedures", repo_root / "procedures")
    ]
    for i, (name, path) in enumerate(boot_files):
        is_final = (i == len(boot_files)-1)
        if path.exists():
            content = "Dir Loaded." if path.is_dir() else path.read_text()
            state.input_queue.put(("boot_packet", {"name": name, "content": content, "is_final_boot": is_final}))

    # 4. MAIN UI REFRESH LOOP
    layout = UIBuilder.make_layout()
    layout["header"].update(Panel(Text.from_markup(ASCII_BANNER), box=ROUNDED, border_style="dim"))
    layout["divider"].update(Rule(style="dim blue"))

    with Live(layout, refresh_per_second=10, screen=True):
        while not state.exit_requested:
            layout["history"].update(UIBuilder.render_history(state))
            layout["logic"].update(UIBuilder.render_logic(state))
            layout["footer"].update(UIBuilder.render_footer(state))
            
            # Update Feedback Line
            if not state.boot_complete:
                help_text = "(feel free to start queuing up work while i boot...)"
            elif state.processing:
                help_text = f"(roger that, msg {state.input_queue.qsize()} queued... feel free to type next prompt)"
            else:
                help_text = "(system ready for mission input)"
            layout["feedback"].update(Text(help_text, style="dim grey70 italic", justify="center"))
            
            time.sleep(0.1)

if __name__ == "__main__":
    main()
    console.print("\n[bold blue]AI-ADMIN SESSION CLOSED.[/]")
