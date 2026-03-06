#!/usr/bin/env python3
"""ollama-headless-chat-v2.py

A beautiful terminal UI for interacting with the ollama-headless agent.
Uses 'rich' for formatting and 'readline' for history.
Supports real-time thinking display and interactive permission requests.
"""

import sys
import os
import json
import time
import argparse
import readline
import re
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.box import ROUNDED

# Import tools from the runner script
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from ollama_headless.ollama_headless import (
    Policy, Tooling, OllamaClient, tool_schema, boot_sequence, 
    heuristic_extract_tool_calls, now_iso
)

console = Console()

class ChatUI:
    def __init__(self, role, model):
        self.role = role
        self.model = model
        self.history_file = Path.home() / ".ollama_headless_chat_history"
        self._setup_readline()

    def _setup_readline(self):
        if self.history_file.exists():
            readline.read_history_file(str(self.history_file))
        readline.set_history_length(1000)

    def save_history(self):
        readline.write_history_file(str(self.history_file))

    def print_banner(self, unrestricted=False):
        mode = "[bold red]UNRESTRICTED[/]" if unrestricted else "[bold green]RESTRICTED[/]"
        console.print(Panel(
            Text.from_markup(f"[bold blue]Ollama Headless Chat v2[/]\n[dim]Role:[/] [cyan]{self.role}[/] | [dim]Model:[/] [green]{self.model}[/] | [dim]Mode:[/] {mode}"),
            border_style="blue",
            box=ROUNDED
        ))

    def get_input(self):
        try:
            return console.input(f"[bold magenta]ollama[{self.role}]>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            return None

    def display_message(self, role, content):
        if role == "user":
            pass 
        elif role == "assistant":
            if content:
                console.print(Panel(Markdown(content), title="Assistant", border_style="green", box=ROUNDED))

class ProgressManager:
    def __init__(self, live):
        self.steps = []
        self.live = live
        self.current_content = ""

    def add_step(self, msg, style="dim yellow"):
        self.steps.append(Text.from_markup(msg, style=style))
        self.refresh()

    def update_content(self, content):
        self.current_content = content
        self.refresh()

    def refresh(self):
        if not self.live: return
        
        main_table = Table.grid(expand=True)
        
        # 1. Thinking / Content Section - DARK THEME
        if self.current_content:
            main_table.add_row(Panel(
                Text(self.current_content, style="grey70 on grey15"), 
                title="Thinking...", 
                border_style="dim"
            ))
        
        # 2. Progress Steps Section
        steps_table = Table.grid(expand=True)
        for s in self.steps[-10:]:
            steps_table.add_row(Text("• ") + s)
        
        main_table.add_row(steps_table)
        self.live.update(main_table)

def update_policy_file(policy_path, new_pattern):
    """Safely adds a new pattern to the allow_patterns list in policy.yaml."""
    try:
        content = policy_path.read_text()
        if "allow_patterns:" in content:
            new_line = f"    - \"{new_pattern}\"\n"
            content = content.replace("allow_patterns:\n", f"allow_patterns:\n{new_line}")
            policy_path.write_text(content)
            return True
    except Exception as e:
        console.print(f"[bold red]Error updating policy:[/] {e}")
    return False

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--role", default="sysadmin")
    ap.add_argument("--model", default=None)
    ap.add_argument("--unrestricted", action="store_true", help="Use unrestricted policy mode")
    args = ap.parse_args()

    repo_root = Path(args.repo).resolve()
    
    policy_name = "unrestricted_policy.yaml" if args.unrestricted else "policy.yaml"
    policy_path = repo_root / "scripts" / "ollama_headless" / policy_name
    audit_path = Path("/var/log/ai-admin/ollama_headless_audit.jsonl")

    policy = Policy.from_file(policy_path, repo_root, allow_unsafe_cmds=args.unrestricted)
    tooling = Tooling(policy, audit_path)
    client = OllamaClient(policy.ollama_base_url)
    model = args.model or policy.__dict__.get("default_model", "qwen3-coder:latest")

    ui = ChatUI(args.role, model)
    ui.print_banner(unrestricted=args.unrestricted)

    if not client.preflight(model):
        console.print(f"[bold red]FATAL:[/] Model '{model}' not found in Ollama.")
        sys.exit(1)

    with console.status("[bold blue]Booting agent...") as status:
        boot_context = boot_sequence(repo_root, args.role, tooling)

    system = (
        f"### MISSION ARCHITECTURE: AI-ADMIN AUTONOMOUS UNIT\n"
        f"IDENTITY: You are an autonomous agent operating as the '{args.role}' role in CHAT MODE.\n"
        f"CORE DIRECTIVE: Analyze provided MISSION MANIFEST, identify pending work, and execute using TOOLS.\n\n"
        f"### OPERATIONAL RULES:\n"
        f"1. SOURCE OF TRUTH: The MISSION MANIFEST provided in the first message is your foundation. Read it. Believe it.\n"
        f"2. ACTION OVER CHAT: Call tools immediately. Do not explain what you are about to do unless it is complex.\n"
        f"3. NO GUESSING: If you need to know a file structure, use list_files. Never hallucinate paths.\n"
        f"4. SELF-CORRECTION: If a tool fails, analyze the error and pivot strategy.\n"
        f"5. PERMISSION: If a command is blocked, use 'request_permission' immediately.\n"
        f"6. CHAT MODE: You are talking to a human. Be concise, transparent, and helpful.\n\n"
        f"Available tools: list_files, read_file, write_file, run_cmd, grep_search, git_status, git_diff, git_stash, git_pop, git_commit, git_push, request_permission."
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"### START MISSION\n\n{boot_context}\n\n### INITIAL TASK\nPlease acknowledge your role and the mission parameters above. Waiting for instructions."}
    ]

    while True:
        user_input = ui.get_input()
        if user_input is None or user_input.lower() in ["exit", "quit", ":q"]:
            ui.save_history()
            break
        if not user_input: continue

        messages.append({"role": "user", "content": user_input})
        
        with Live(Table.grid(), refresh_per_second=4) as live:
            pm = ProgressManager(live)
            
            # Agent Loop
            for step in range(1, 25):
                pm.add_step(f"Step {step}: Model call...", style="bold yellow")
                # IMPORTANT: we now pass options with num_ctx to OllamaClient.chat
                resp = client.chat(model=model, messages=messages, tools=tool_schema())
                
                if "error" in resp:
                    pm.add_step(f"FATAL: {resp['error']}", style="bold red")
                    live.stop()
                    break

                msg = resp.get("message") or {}
                messages.append(msg)

                content = (msg.get("content") or "").strip()
                if content: pm.update_content(content)
                
                tool_calls = msg.get("tool_calls") or []

                if not tool_calls:
                    tool_calls = heuristic_extract_tool_calls(content)
                    if not tool_calls:
                        live.stop()
                        ui.display_message("assistant", content)
                        break
                    pm.add_step(f"Heuristic: extracted [bold]{len(tool_calls)}[/] calls.", style="magenta")

                for call in tool_calls:
                    fn_info = call.get("function") or {}
                    fn_name = fn_info.get("name")
                    raw_args = fn_info.get("arguments")
                    
                    if isinstance(raw_args, str):
                        try: fn_args = json.loads(raw_args)
                        except: fn_args = {}
                    else: fn_args = raw_args or {}

                    pm.add_step(f"Tool: [bold cyan]{fn_name}[/] args={fn_args}", style="cyan")
                    
                    if fn_name == "request_permission":
                        live.stop()
                        console.print(Panel(
                            f"[bold yellow]Permission Requested:[/] {fn_args.get('reason')}\n[bold]Pattern:[/] [green]{fn_args.get('cmd_pattern')}[/]",
                            title="Authorization Required", border_style="yellow"
                        ))
                        choice = console.input("[bold red]Authorize this pattern? (y/N): [/]").strip().lower()
                        if choice == 'y':
                            if update_policy_file(policy_path, fn_args.get('cmd_pattern')):
                                out = {"status": "APPROVED", "message": "Policy updated. You can now run the command."}
                                tooling.policy = Policy.from_file(policy_path, repo_root, allow_unsafe_cmds=args.unrestricted)
                            else:
                                out = {"status": "ERROR", "message": "Failed to update policy file."}
                        else:
                            out = {"status": "DENIED", "message": "User refused to authorize this pattern."}
                        live.start()
                    else:
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
                        except Exception as e:
                            out = {"error": str(e)}

                    if "error" in out:
                        pm.add_step(f"[bold red]Error:[/] {out['error']}", style="red")

                    if fn_name in ["run_cmd", "grep_search"] and "stdout" in out:
                        if out["stdout"]: pm.add_step(f"[dim]Stdout:[/]\n{out['stdout'][:500]}", style="green")
                        if out["stderr"]: pm.add_step(f"[dim]Stderr:[/]\n{out['stderr'][:500]}", style="red")
                    elif fn_name == "read_file" and "content" in out:
                        pm.add_step(f"[dim]Read:[/] {len(out['content'])} bytes", style="green")

                    messages.append({"role": "tool", "name": fn_name, "content": json.dumps(out)})
        
        console.print()

if __name__ == "__main__":
    main()
