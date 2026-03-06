#!/usr/bin/env python3
"""ollama-headless-chat-v6.py

Terminal chat UI for the AI-Admin ollama-headless lane.

v6 goals vs v4/v5:
- No giant hardcoded system prompt strings in code.
  We load system prompt templates from scripts/ollama_headless/prompts/.
- Smarter boot: inject ONE boot context blob (boot_sequence) instead of many
  individual "boot packets".
- Keep UI concerns separate from the runner/tooling layer.
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, "ollama_headless"))

import json
import time
import argparse
import atexit
import threading
import queue
from pathlib import Path

import readline
from rich.console import Console
from rich.panel import Panel
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich.markdown import Markdown
from rich.layout import Layout
from rich.box import ROUNDED
from rich.spinner import Spinner
from rich.rule import Rule
from rich.columns import Columns

# Import tools from repo-local modules by absolute path (avoids name collisions)
import importlib.util

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
OHS_DIR = os.path.join(SCRIPT_DIR, "ollama_headless")

# Load ollama_headless.py
_spec1 = importlib.util.spec_from_file_location("oh_mod", os.path.join(OHS_DIR, "ollama_headless.py"))
oh_mod = importlib.util.module_from_spec(_spec1)
sys.modules[_spec1.name] = oh_mod
assert _spec1 and _spec1.loader
_spec1.loader.exec_module(oh_mod)

Policy = oh_mod.Policy
Tooling = oh_mod.Tooling
OllamaClient = oh_mod.OllamaClient
tool_schema = oh_mod.tool_schema
boot_sequence = oh_mod.boot_sequence
heuristic_extract_tool_calls = oh_mod.heuristic_extract_tool_calls

# Load prompt_loader.py
_spec2 = importlib.util.spec_from_file_location("pl_mod", os.path.join(OHS_DIR, "prompt_loader.py"))
pl_mod = importlib.util.module_from_spec(_spec2)
sys.modules[_spec2.name] = pl_mod
assert _spec2 and _spec2.loader
_spec2.loader.exec_module(pl_mod)

load_system_prompt = pl_mod.load_system_prompt
DEFAULT_TOOLS = pl_mod.DEFAULT_TOOLS


VERSION = "v6.0.0"
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
    def __init__(self, role: str, model: str, unrestricted: bool):
        self.role = role
        self.model = model
        self.unrestricted = unrestricted
        self.tokens_used = 0

        self.history = []  # (role, content)
        self.messages = []  # ollama chat payload history

        self.processing = False
        self.current_thinking = ""
        self.current_steps = []

        self.input_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.exit_requested = False

    def update_tokens(self, meta: dict):
        self.tokens_used = meta.get("prompt_eval_count", 0) + meta.get("eval_count", 0)


class UIBuilder:
    @staticmethod
    def make_layout() -> Layout:
        layout = Layout()
        layout.split(
            Layout(name="header", size=8),
            Layout(name="body", ratio=1),
            Layout(name="divider", size=1),
            Layout(name="feedback", size=1),
            Layout(name="footer", size=3),
        )
        layout["body"].split_row(
            Layout(name="history", ratio=2),
            Layout(name="logic", ratio=1),
        )
        return layout

    @staticmethod
    def render_history(state: ChatState):
        table = Table.grid(expand=True)
        for role, content in state.history[-8:]:
            if role == "user":
                table.add_row(
                    Panel(
                        Text(content, style="bright_white"),
                        title="[bold magenta]USER[/]",
                        border_style="magenta",
                        box=ROUNDED,
                    )
                )
            elif role == "assistant":
                table.add_row(
                    Panel(
                        Markdown(content),
                        title="[bold green]ASSISTANT[/]",
                        border_style="green",
                        box=ROUNDED,
                    )
                )

        if state.processing and state.current_thinking:
            table.add_row(
                Panel(
                    Text(state.current_thinking, style="grey70 on grey15"),
                    title="[italic blue]Thinking...[/]",
                    border_style="blue",
                )
            )
        return table

    @staticmethod
    def render_logic(state: ChatState):
        steps_table = Table.grid(expand=True)
        for s in state.current_steps[-25:]:
            steps_table.add_row(Text(" • ") + Text.from_markup(s))

        if state.processing:
            if not state.current_thinking:
                steps_table.add_row(Columns([Text(" • "), Text("Analyzing... ", style="dim"), Spinner("dots")], padding=0))
            else:
                steps_table.add_row(Columns([Text(" • "), Text("Streaming... ", style="cyan"), Spinner("bouncingBar")], padding=0))

        return Panel(steps_table, title="[bold yellow]Agent Logic[/]", border_style="yellow", box=ROUNDED)

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
            Text.from_markup(f"Context: [{ctx_color}]{ctx_pct:.1f}%[/] [dim]({state.tokens_used // 1000}k/{MAX_CTX // 1000}k)[/] "),
        )
        return Panel(grid, style="cyan on grey11", box=ROUNDED)


def setup_history():
    history_file = Path.home() / ".ollama_headless_v6_history"
    if history_file.exists():
        try:
            readline.read_history_file(str(history_file))
        except Exception:
            pass
    readline.set_history_length(2000)
    atexit.register(readline.write_history_file, str(history_file))


def agent_worker(state: ChatState, client: OllamaClient, model: str, tooling: Tooling):
    while not state.exit_requested:
        try:
            kind, data = state.input_queue.get(timeout=0.1)
        except queue.Empty:
            continue

        if kind == "STOP":
            break

        state.processing = True
        state.current_thinking = ""
        state.current_steps = []

        if kind == "USER":
            user_text = data
            state.history.append(("user", user_text))
            state.messages.append({"role": "user", "content": user_text})

            for step in range(1, 25):
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
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                state.messages.append(assistant_msg)

                if not tool_calls:
                    tool_calls = heuristic_extract_tool_calls(full_content)
                    if not tool_calls:
                        state.history.append(("assistant", full_content))
                        state.current_steps.append("[green]Turn Complete.[/]")
                        break

                for call in tool_calls:
                    fn_info = call.get("function") or {}
                    fn_name = fn_info.get("name")
                    raw_args = fn_info.get("arguments")
                    fn_args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})

                    state.current_steps.append(f"Tool: [bold cyan]{fn_name}[/]")
                    try:
                        if fn_name == "list_files":
                            out = tooling.list_files(**fn_args)
                        elif fn_name == "read_file":
                            out = tooling.read_file(**fn_args)
                        elif fn_name == "write_file":
                            out = tooling.write_file(**fn_args)
                        elif fn_name == "run_cmd":
                            out = tooling.run_cmd(**fn_args)
                        elif fn_name == "grep_search":
                            out = tooling.grep_search(**fn_args)
                        elif fn_name == "git_status":
                            out = tooling.git_status()
                        elif fn_name == "git_diff":
                            out = tooling.git_diff()
                        elif fn_name == "git_stash":
                            out = tooling.git_stash()
                        elif fn_name == "git_pop":
                            out = tooling.git_pop()
                        elif fn_name == "git_commit":
                            out = tooling.git_commit(**fn_args)
                        elif fn_name == "git_push":
                            out = tooling.git_push(**fn_args)
                        else:
                            out = {"error": f"Unknown tool: {fn_name}"}
                    except Exception as e:
                        out = {"error": str(e)}

                    res_str = str(out).replace("\n", " ")
                    state.current_steps.append(f"Result: [dim]{res_str[:160]}...[/]")
                    state.messages.append({"role": "tool", "name": fn_name, "content": json.dumps(out)})

        state.processing = False
        state.current_thinking = ""
        state.current_steps = []
        state.input_queue.task_done()


def input_thread(state: ChatState):
    while not state.exit_requested:
        try:
            user_input = console.input("[bold magenta]prompt>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            state.exit_requested = True
            break

        if user_input.lower() in {"exit", "quit", ":q"}:
            state.exit_requested = True
            break

        if user_input:
            state.input_queue.put(("USER", user_input))


def main():
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

    # Boot once: system prompt templates + compiled boot_sequence context.
    system = load_system_prompt(repo_root, args.role, mode="chat", tools=DEFAULT_TOOLS)
    boot_context = boot_sequence(repo_root, args.role, tooling)
    state.messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                "### START MISSION\n\n"
                + boot_context
                + "\n\n### INITIAL TASK\nAcknowledge role and confirm you will use tools-first."
            ),
        },
    ]

    # Prime: single non-stream chat call so the model "locks in" the mission.
    state.processing = True
    state.current_steps = ["Boot: priming model with mission context..."]
    resp = client.chat(model=model, messages=state.messages, tools=[])
    msg = resp.get("message") or {"role": "assistant", "content": "Acknowledged."}
    state.messages.append(msg)
    if "content" in msg:
        state.history.append(("assistant", msg["content"]))
    state.update_tokens(resp)
    state.processing = False
    state.current_steps = []

    # Start background threads
    worker = threading.Thread(target=agent_worker, args=(state, client, model, tooling), daemon=True)
    worker.start()
    in_thread = threading.Thread(target=input_thread, args=(state,), daemon=True)
    in_thread.start()

    # UI loop
    layout = UIBuilder.make_layout()
    layout["header"].update(Panel(Text.from_markup(ASCII_BANNER), box=ROUNDED, border_style="dim"))
    layout["divider"].update(Rule(style="dim blue"))

    with Live(layout, refresh_per_second=10, screen=True):
        while not state.exit_requested:
            layout["history"].update(UIBuilder.render_history(state))
            layout["logic"].update(UIBuilder.render_logic(state))
            layout["footer"].update(UIBuilder.render_footer(state))
            layout["feedback"].update(
                Text(
                    "(type a prompt, or 'exit')" if not state.processing else "(working… you can queue another prompt)",
                    style="dim grey70 italic",
                    justify="center",
                )
            )
            time.sleep(0.1)

    state.input_queue.put(("STOP", ""))


if __name__ == "__main__":
    main()
    console.print("\n[bold blue]AI-ADMIN SESSION CLOSED.[/]")

