#!/usr/bin/env python3
"""ollama-headless-chat-v4.py (v4.6.1)

Advanced Terminal UI for AI-Admin Unit.
Features: 32k Context, Interactive Boot Log, Primed Layout,
and Side-by-side Logic Panel with fixed Spinner rendering.
"""

import sys
import os
import json
import time
import argparse
import readline
import atexit
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

VERSION = "v4.6.1"
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
        self.history = []
        self.current_thinking = ""
        self.current_steps = []
        self.last_user_prompt = ""
        self.processing = False
        self.wave_index = 0

    def update_tokens(self, meta):
        self.tokens_used = meta.get("prompt_eval_count", 0) + meta.get("eval_count", 0)

class UIBuilder:
    @staticmethod
    def make_layout() -> Layout:
        layout = Layout()
        layout.split(
            Layout(name="header", size=8),
            Layout(name="body", ratio=1),
            Layout(name="divider", size=1),
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
            table.add_row(Panel(Text(state.last_user_prompt, style="bright_white"), title="[bold magenta]USER (processing...)[/]", border_style="magenta", box=ROUNDED))
            if state.current_thinking:
                table.add_row(Panel(Text(state.current_thinking, style="grey70 on grey15"), title="[italic blue]Thinking...[/]", border_style="blue"))
        return table

    @staticmethod
    def render_logic(state: ChatState):
        table = Table.grid(expand=True)
        if state.processing:
            steps_table = Table.grid(expand=True)
            for s in state.current_steps[-20:]:
                steps_table.add_row(Text(" • ") + Text.from_markup(s))
            
            # v4.6.1 FIX: Use Columns to safely combine Text and Spinner
            if not state.current_thinking:
                steps_table.add_row(Columns([Text(" • "), Text("Processing turn... ", style="dim"), Spinner("dots")], padding=0))
            else:
                steps_table.add_row(Columns([Text(" • "), Text("Generating response... ", style="cyan"), Spinner("bouncingBar")], padding=0))
                
            table.add_row(Panel(steps_table, title="[bold yellow]Agent Logic[/]", border_style="yellow", box=ROUNDED))
        else:
            table.add_row(Panel(Text("\n\nAgent Idle.\nStanding by for mission.", style="dim center", justify="center"), title="[dim]Status[/]", border_style="dim", box=ROUNDED))
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

def execute_turn(state, client, model, messages, layout, live):
    """Encapsulates a single agent turn with UI updates."""
    state.processing = True
    state.current_steps = []
    state.current_thinking = ""
    
    for step in range(1, 25):
        state.current_thinking = ""
        state.current_steps.append(f"Step {step}: Model call...")
        
        layout["history"].update(UIBuilder.render_history(state))
        layout["logic"].update(UIBuilder.render_logic(state))
        live.update(layout)
        
        full_content = ""
        tool_calls = []
        
        for chunk in client.chat_stream(model=model, messages=messages, tools=tool_schema()):
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
            
            layout["history"].update(UIBuilder.render_history(state))
            layout["logic"].update(UIBuilder.render_logic(state))
            layout["footer"].update(UIBuilder.render_footer(state))
            live.update(layout)

        assistant_msg = {"role": "assistant", "content": full_content}
        if tool_calls: assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        if not tool_calls:
            tool_calls = heuristic_extract_tool_calls(full_content)
            if not tool_calls:
                state.history.append(("assistant", full_content))
                state.processing = False
                state.last_user_prompt = ""
                state.current_thinking = ""
                state.current_steps = []
                layout["history"].update(UIBuilder.render_history(state))
                layout["logic"].update(UIBuilder.render_logic(state))
                layout["footer"].update(UIBuilder.render_footer(state))
                live.update(layout)
                return
            state.current_steps.append(f"Heuristic: found {len(tool_calls)} calls.")

        for call in tool_calls:
            fn_info = call.get("function") or {}
            fn_name = fn_info.get("name")
            raw_args = fn_info.get("arguments")
            fn_args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            
            state.current_steps.append(f"Tool: [bold cyan]{fn_name}[/]")
            live.update(layout)
            
            if fn_name == "request_permission":
                live.stop()
                console.print(Panel(f"{fn_args.get('reason')}\nPattern: [green]{fn_args.get('cmd_pattern')}[/]", title="Permission Request", border_style="yellow"))
                if console.input("[red]Authorize? (y/N): [/]").lower() == 'y':
                    out = {"status": "APPROVED", "message": "Policy updated."}
                else:
                    out = {"status": "DENIED", "message": "Refused."}
                live.start()
            else:
                try:
                    from __main__ import tooling
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
            state.current_steps.append(f"Result: [dim]{res_str[:500]}...[/]")
            messages.append({"role": "tool", "name": fn_name, "content": json.dumps(out)})
            
            layout["history"].update(UIBuilder.render_history(state))
            layout["logic"].update(UIBuilder.render_logic(state))
            layout["footer"].update(UIBuilder.render_footer(state))
            live.update(layout)

def setup_history():
    history_file = Path.home() / ".ollama_headless_v4_history"
    if history_file.exists():
        try: readline.read_history_file(str(history_file))
        except: pass
    readline.set_history_length(1000)
    atexit.register(readline.write_history_file, str(history_file))

def main():
    global tooling
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--role", default="sysadmin")
    ap.add_argument("--model", default=None)
    ap.add_argument("--unrestricted", action="store_true")
    args = ap.parse_args()

    repo_root = Path(args.repo).resolve()
    policy_name = "unrestricted_policy.yaml" if args.unrestricted else "policy.yaml"
    policy_path = repo_root / "scripts" / "ollama_headless" / policy_name
    audit_path = Path("/var/log/ai-admin/ollama_headless_audit.jsonl")

    policy = Policy.from_file(policy_path, repo_root, allow_unsafe_cmds=args.unrestricted)
    tooling = Tooling(policy, audit_path)
    client = OllamaClient(policy.ollama_base_url)
    model = args.model or policy.__dict__.get("default_model", "qwen3-coder:latest")

    state = ChatState(args.role, model, args.unrestricted)
    setup_history()

    # 1. PRIME LAYOUT
    layout = UIBuilder.make_layout()
    layout["header"].update(Panel(Text.from_markup(ASCII_BANNER), box=ROUNDED, border_style="dim"))
    layout["divider"].update(Rule(style="dim blue"))
    layout["history"].update(UIBuilder.render_history(state))
    layout["logic"].update(UIBuilder.render_logic(state))
    layout["footer"].update(UIBuilder.render_footer(state))

    console.clear()
    
    # 2. INTERACTIVE BOOT
    state.processing = True
    with Live(layout, refresh_per_second=10, screen=False) as live:
        state.current_steps.append("[bold cyan]PHASE 1: BOOTING DIRECTIVES[/]")
        
        manifest_files = ["README.md", "AGENTS.md", f"roles/{args.role}.md", "Procedures (Core Set)"]
        for f in manifest_files:
            time.sleep(0.1)
            state.current_steps.append(f"Loading {f}...")
            live.update(layout)
            
        boot_context = boot_sequence(repo_root, args.role, tooling)
        
        state.current_steps.append("[bold cyan]PHASE 2: MISSION START[/]")
        state.last_user_prompt = "BOOT SEQUENCE"
        
        system = (
            f"### MISSION ARCHITECTURE: AI-ADMIN AUTONOMOUS UNIT\n"
            f"IDENTITY: You are an autonomous agent operating as the '{args.role}' role in CHAT MODE.\n"
            f"CORE DIRECTIVE: Analyze provided CORE MISSION DIRECTIVES and execute using TOOLS.\n\n"
            f"### OPERATIONAL RULES:\n"
            f"1. SOURCE OF TRUTH: CORE MISSION DIRECTIVES are your foundation. Embedded in prompt.\n"
            f"2. ACTION OVER CHAT: Call tools immediately.\n"
            f"3. NO GUESSING: Never hallucinate paths. Use list_files.\n"
            f"Available tools: list_files, read_file, write_file, run_cmd, grep_search, git_status, git_diff, git_stash, git_pop, git_commit, git_push, request_permission."
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"### START MISSION\n\n{boot_context}\n\n### INITIAL TASK\nAcknowledge role and core mission focus."}
        ]
        
        execute_turn(state, client, model, messages, layout, live)

    # 3. MAIN INTERACTIVE LOOP
    while True:
        layout["history"].update(UIBuilder.render_history(state))
        layout["logic"].update(UIBuilder.render_logic(state))
        layout["footer"].update(UIBuilder.render_footer(state))
        console.clear()
        console.print(layout)

        try:
            user_input = console.input(f"[bold magenta]ollama[{args.role}]>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break
        if not user_input: continue
        if user_input.lower() in ["exit", "quit", ":q"]: break

        state.last_user_prompt = user_input
        messages.append({"role": "user", "content": user_input})
        
        with Live(layout, refresh_per_second=10, screen=False) as live:
            try:
                execute_turn(state, client, model, messages, layout, live)
            except KeyboardInterrupt:
                state.processing = False
                state.last_user_prompt = ""
                continue

if __name__ == "__main__":
    main()
