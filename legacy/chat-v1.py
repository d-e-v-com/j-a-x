#!/usr/bin/env python3
"""ollama-headless-chat.py

Interactive chat wrapper for the ollama-headless agent.
Allows multi-turn conversations with the same agent state, 
while still performing autonomous tool steps between turns.
"""

import sys
import os
import json
import time
import argparse
from pathlib import Path

# Add repo root to path so we can import ollama_headless if it were a module,
# but since it's a script, we'll just import its classes/functions by absolute path.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from ollama_headless.ollama_headless import (
    Policy, Tooling, OllamaClient, tool_schema, boot_sequence, 
    heuristic_extract_tool_calls, progress, now_iso
)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--role", default="sysadmin")
    ap.add_argument("--model", default=None)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--max-steps", type=int, default=20)
    args = ap.parse_args()

    repo_root = Path(args.repo).resolve()
    policy_path = repo_root / "scripts" / "ollama_headless" / "policy.yaml"
    audit_path = Path("/var/log/ai-admin/ollama_headless_audit.jsonl")

    policy = Policy.from_file(policy_path, repo_root, allow_unsafe_cmds=False)
    tooling = Tooling(policy, audit_path)
    client = OllamaClient(policy.ollama_base_url)

    model = args.model or policy.__dict__.get("default_model", "qwen3-coder:latest")

    print(f"--- ollama-headless-chat ---")
    print(f"Role: {args.role} | Model: {model}")
    print(f"Type 'exit' or 'quit' to end session.")
    print(f"-----------------------------")

    if not client.preflight(model):
        print(f"FATAL: Model '{model}' not found in Ollama.")
        sys.exit(1)

    boot_context = boot_sequence(repo_root, args.role, tooling)
    
    system = (
        "You are ollama-headless, a fully headless autonomous agent running inside a git repo. "
        "Available tools: list_files, read_file, write_file, run_cmd, git_status, git_diff, git_commit, git_push. "
        "YOU MUST USE THESE TOOLS. Do not write code blocks or explanations unless asked. "
        "ACTION FIRST: Call tools immediately to perform the requested task. "
        "SELF-CORRECTION: If a tool call fails, analyze the error, adjust your approach, and try again. "
        "SELF-AUDIT: Before you finish, you MUST list all files you created or modified and verify their contents. "
        "This is to detect hallucinations or unintended artifacts. Clean up any unintended files. "
        "POLICY-DEBT: If a command you need is blocked by policy, DO NOT try to bypass it. "
        "Instead, document the blocked command in your final summary for human review. "
        "DYNAMIC TOOLS: For complex shell tasks, write a script to 'scripts/tmp/', chmod +x it, and run it. "
        "HYBRID MODE: If your model does not support native tool calling, output markdown code blocks. "
        "Example: ```bash\nls -la\n``` will be executed as run_cmd. "
        "COMMIT & PUSH: Before you finish, you MUST check git status, commit any changes you made, and push to origin. "
        "CHAT MODE: You are talking to a human. After you perform your tool steps, output your final answer and wait for further instructions."
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Context and Procedures:\n\n{boot_context}\n\nSession started. Waiting for instructions."}
    ]

    tools = tool_schema()

    while True:
        try:
            user_input = input(f"ollama[{args.role}]> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if user_input.lower() in ["exit", "quit", ":q"]:
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        # Run agent loop for this turn
        turn_start = time.time()
        for step in range(1, args.max_steps + 1):
            if time.time() - turn_start > args.timeout:
                print(f"TIMEOUT reached.")
                break

            progress(f"Step {step}: Model call...")
            resp = client.chat(model=model, messages=messages, tools=tools)
            msg = resp.get("message") or {}
            messages.append(msg)

            content = (msg.get("content") or "").strip()
            tool_calls = msg.get("tool_calls") or []

            if content:
                print(content, flush=True)

            if not tool_calls:
                # Try heuristic extraction
                tool_calls = heuristic_extract_tool_calls(content)
                if not tool_calls:
                    # Turn complete
                    break
                progress(f"Heuristic: extracted {len(tool_calls)} tool calls.")

            for call in tool_calls:
                fn_info = call.get("function") or {}
                fn_name = fn_info.get("name")
                raw_args = fn_info.get("arguments")
                
                if isinstance(raw_args, str):
                    try: fn_args = json.loads(raw_args) if raw_args else {}
                    except Exception: fn_args = {}
                else:
                    fn_args = raw_args or {}

                progress(f"Tool call: {fn_name}({fn_args})")
                try:
                    if fn_name == "list_files":
                        out = tooling.list_files(glob=str(fn_args.get("glob", "**/*")), max_items=int(fn_args.get("max_items", 4000)))
                    elif fn_name == "read_file":
                        out = tooling.read_file(relpath=str(fn_args["relpath"]))
                    elif fn_name == "write_file":
                        out = tooling.write_file(relpath=str(fn_args["relpath"]), content=str(fn_args["content"]))
                    elif fn_name == "run_cmd":
                        out = tooling.run_cmd(cmd=str(fn_args["cmd"]), timeout_s=int(fn_args.get("timeout_s", 120)))
                    elif fn_name == "git_status":
                        out = tooling.git_status()
                    elif fn_name == "git_diff":
                        out = tooling.git_diff()
                    elif fn_name == "git_commit":
                        out = tooling.git_commit(message=str(fn_args["message"]))
                    elif fn_name == "git_push":
                        out = tooling.git_push(remote=fn_args.get("remote"), branch=fn_args.get("branch"))
                    else:
                        out = {"error": f"Unknown tool: {fn_name}"}
                except Exception as e:
                    out = {"error": str(e)}

                messages.append({"role": "tool", "name": fn_name, "content": json.dumps(out)})
        
        print() # Newline after turn

if __name__ == "__main__":
    main()
