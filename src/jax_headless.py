#!/usr/bin/env python3
"""jax_headless.py

JAX — Headless AI Agent Runner.

Runs autonomous agent loops against Ollama models with tool-calling
and YAML-based security policy enforcement.

Originally built as ollama_headless.py in RoboTrader-io/Ai-admin (Feb–Mar 2026).
Carved out and rebranded as JAX under d-e-v-com/j-a-x.

This runner:
  - Uses Ollama's /api/chat with tool calling
  - Provides a guarded tool layer for repo work
  - Runs an agent loop until the model stops calling tools or step limit hit
  - Supports hybrid tool extraction (native + markdown parsing)
  - Supports Restricted vs Unrestricted policy modes
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import shlex
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Keep this runner drop-in friendly (works when executed as a script or imported
# from sibling chat UIs). We avoid package-relative imports.
try:
    from prompt_loader import load_system_prompt, DEFAULT_TOOLS  # type: ignore
except Exception:  # pragma: no cover
    DEFAULT_TOOLS = [
        "list_files",
        "read_file",
        "write_file",
        "run_cmd",
        "grep_search",
        "git_status",
        "git_diff",
        "git_stash",
        "git_pop",
        "git_commit",
        "git_push",
        "request_permission",
    ]

    def load_system_prompt(repo_root: Path, role: str, mode: str, tools=DEFAULT_TOOLS) -> str:  # type: ignore
        return (
            "### AI-ADMIN AUTONOMOUS UNIT\n"
            f"IDENTITY: {role}\nMODE: {mode}\n\n"
            "Use tools immediately. Never guess paths; use list_files first.\n"
            f"Tools: {', '.join(list(tools))}"
        )


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr, flush=True)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def progress(msg: str) -> None:
    eprint(f"[{now_iso()}] {msg}")


def load_yaml_minimal(path: Path) -> Dict[str, Any]:
    """Tiny YAML loader for the limited policy.yaml structure."""
    try:
        import yaml  # type: ignore

        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        # Fallback parser if yaml not installed
        data: Dict[str, Any] = {}
        cur_stack: List[Tuple[int, Dict[str, Any] | List[Any]]] = [(0, data)]

        def current_container() -> Dict[str, Any] | List[Any]:
            return cur_stack[-1][1]

        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.rstrip()
            if not line or line.lstrip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip())
            line = line.lstrip()
            while cur_stack and indent < cur_stack[-1][0]:
                cur_stack.pop()

            if line.startswith("- "):
                item = line[2:].strip().strip('"').strip("'")
                cont = current_container()
                if isinstance(cont, list):
                    cont.append(item)
                continue

            if ":" in line:
                parts = line.split(":", 1)
                k = parts[0].strip()
                v = parts[1].strip() if len(parts) > 1 else ""
                cont = current_container()
                if not isinstance(cont, dict):
                    continue
                if v == "":
                    new_d: Dict[str, Any] = {}
                    cont[k] = new_d
                    cur_stack.append((indent + 2, new_d))
                else:
                    cont[k] = v.strip().strip('"').strip("'")
        return data


@dataclass
class Policy:
    repo_root: Path
    max_read_bytes: int = 250_000
    max_write_bytes: int = 500_000
    deny_patterns: List[re.Pattern] = None  # type: ignore
    allow_patterns: List[re.Pattern] = None  # type: ignore
    allow_unsafe_cmds: bool = False
    default_remote: str = "origin"
    default_branch: str = "main"
    ollama_base_url: str = "http://127.0.0.1:11434"

    @staticmethod
    def from_file(policy_path: Path, repo_root: Path, allow_unsafe_cmds: bool) -> "Policy":
        base = Policy(repo_root=repo_root, allow_unsafe_cmds=allow_unsafe_cmds)
        if not policy_path.exists():
            base.deny_patterns = [re.compile(r"\bsudo\b"), re.compile(r"rm\s+-rf")]
            base.allow_patterns = [re.compile(r"^git (status|diff|log|add|commit|push|pull)( .*)?$")]
            return base

        raw = load_yaml_minimal(policy_path)
        files = raw.get("files", {})
        base.max_read_bytes = int(files.get("max_read_bytes", base.max_read_bytes))
        base.max_write_bytes = int(files.get("max_write_bytes", base.max_write_bytes))

        cmds = raw.get("commands", {})
        deny = cmds.get("deny_patterns", [])
        allow = cmds.get("allow_patterns", [])
        base.deny_patterns = [re.compile(p) for p in deny]
        base.allow_patterns = [re.compile(p) for p in allow]

        git = raw.get("git", {})
        base.default_remote = str(git.get("default_remote", base.default_remote))
        base.default_branch = str(git.get("default_branch", base.default_branch))

        ollama = raw.get("ollama", {})
        env_name = str(ollama.get("base_url_env", "OLLAMA_BASE_URL"))
        default_url = str(ollama.get("default_base_url", base.ollama_base_url))
        base.ollama_base_url = os.environ.get(env_name, default_url)

        return base

    def cmd_denied(self, cmd: str) -> bool:
        return any(p.search(cmd) for p in self.deny_patterns)

    def cmd_allowed(self, cmd: str) -> bool:
        return any(p.search(cmd) for p in self.allow_patterns)


class OllamaClient:
    def __init__(self, base_url: str):
        # Normalize: no /v1, no trailing slash
        self.base_url = base_url.rstrip("/")
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3]
        if self.base_url.endswith("/api"):
            self.base_url = self.base_url[:-4]

    def preflight(self, model: str) -> bool:
        url = f"{self.base_url}/api/tags"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            models = [m["name"] for m in data.get("models", [])]
            if model in models:
                return True
            # Try matching without tag
            if ":" in model:
                base_name = model.split(":")[0]
                if any(m.startswith(base_name + ":") or m == base_name for m in models):
                    return True
            return False
        except Exception as e:
            eprint(f"[{now_iso()}] Preflight check failed for {url}: {e}")
            return False

    def chat(self, model: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "options": {
                "num_ctx": 32768,
                "temperature": 0.1
            }
        }
        
        # Some models don't support tools and Ollama returns 400.
        # If model is deepseek-coder, we might want to skip tools entirely in the payload
        # to avoid the 400, but we'll try a fallback approach.
        
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code == 400 and tools:
                # Retry without tools
                progress(f"Ollama returned 400 (Bad Request). Retrying without native tools for {model}...")
                del payload["tools"]
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=600) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                return json.loads(body)
            if e.code == 500:
                return {"error": "Ollama Server Error (500). This often happens when tool-call parsing fails or context is too large."}
            raise
        except (TimeoutError, socket.timeout):
            return {"error": "Ollama API Timed Out (600s). Local inference is taking too long."}

    def chat_stream(self, model: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]):
        """Yields chunks of the response from Ollama."""
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "stream": True,
            "options": {
                "num_ctx": 32768,
                "temperature": 0.1
            }
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                for line in resp:
                    if not line: continue
                    try:
                        yield json.loads(line.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
        except (TimeoutError, socket.timeout):
            yield {"error": "Ollama API Timed Out (600s)."}
        except Exception as e:
            yield {"error": str(e)}


def audit_append(path: Path, entry: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def safe_repo_path(repo_root: Path, rel: str) -> Path:
    p = (repo_root / rel).resolve()
    if not str(p).startswith(str(repo_root.resolve()) + os.sep):
        if str(p) != str(repo_root.resolve()):
            raise ValueError(f"Path not allowed (outside repo): {rel}")
    return p


def tail(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return "...[truncated]...\n" + s[-limit:]


class Tooling:
    def __init__(self, policy: Policy, audit_path: Path):
        self.policy = policy
        self.audit_path = audit_path

    def _log(self, kind: str, payload: Dict[str, Any]) -> None:
        entry = {"ts": now_iso(), "kind": kind, **payload}
        audit_append(self.audit_path, entry)

    def list_files(self, glob: str = "**/*", max_items: int = 4000) -> Dict[str, Any]:
        root = self.policy.repo_root
        items: List[str] = []
        try:
            for p in root.glob(glob):
                if p.is_file():
                    rel = str(p.relative_to(root))
                    items.append(rel)
                    if len(items) >= max_items:
                        break
        except Exception as e:
            return {"error": str(e)}
        out = {"glob": glob, "count": len(items), "files": items}
        self._log("list_files", {"glob": glob, "count": len(items)})
        return out

    def read_file(self, relpath: str) -> Dict[str, Any]:
        try:
            p = safe_repo_path(self.policy.repo_root, relpath)
            data = p.read_text(encoding="utf-8", errors="replace")
            if len(data.encode("utf-8", errors="replace")) > self.policy.max_read_bytes:
                data = data[: self.policy.max_read_bytes] + "\n...[truncated]..."
            self._log("read_file", {"path": relpath, "bytes": len(data)})
            return {"path": relpath, "content": data}
        except Exception as e:
            return {"error": str(e)}

    def write_file(self, relpath: str, content: str) -> Dict[str, Any]:
        try:
            if len(content.encode("utf-8", errors="replace")) > self.policy.max_write_bytes:
                raise ValueError("Write blocked: content too large")
            p = safe_repo_path(self.policy.repo_root, relpath)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            self._log("write_file", {"path": relpath, "bytes": len(content)})
            return {"ok": True, "path": relpath, "bytes": len(content)}
        except Exception as e:
            return {"error": str(e)}

    def run_cmd(self, cmd: str, timeout_s: int = 120) -> Dict[str, Any]:
        try:
            # 1. Safety Gate: Hard-coded destructive patterns check
            destructive = ["rm -rf /", "mkfs", "dd if=/dev/zero", "> /dev/sda", "reboot", "shutdown"]
            if any(d in cmd for d in destructive):
                raise ValueError(f"CRITICAL SAFETY VIOLATION: Command '{cmd}' is destructive and system-blocked.")

            if self.policy.cmd_denied(cmd):
                raise ValueError("Command blocked by deny policy")
            if not self.policy.cmd_allowed(cmd) and not self.policy.allow_unsafe_cmds:
                raise ValueError("Command blocked (not allowlisted). Use 'request_permission' to authorize this pattern.")

            p = subprocess.run(
                cmd,
                cwd=str(self.policy.repo_root),
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
            out = {
                "cmd": cmd,
                "rc": p.returncode,
                "stdout": tail(p.stdout or "", 6000),
                "stderr": tail(p.stderr or "", 6000),
            }
            self._log("run_cmd", {"cmd": cmd, "rc": p.returncode})
            return out
        except Exception as e:
            return {"error": str(e)}

    def git_status(self) -> Dict[str, Any]:
        return self.run_cmd("git status --porcelain=v1 && git status", timeout_s=60)

    def git_diff(self) -> Dict[str, Any]:
        return self.run_cmd("git diff --stat && git diff", timeout_s=120)

    def git_stash(self) -> Dict[str, Any]:
        return self.run_cmd("git stash", timeout_s=60)

    def git_pop(self) -> Dict[str, Any]:
        return self.run_cmd("git stash pop", timeout_s=60)

    def git_commit(self, message: str) -> Dict[str, Any]:
        msg = shlex.quote(message)
        self.run_cmd("git add -A", timeout_s=60)
        return self.run_cmd(f"git commit -m {msg}", timeout_s=120)

    def git_push(self, remote: Optional[str] = None, branch: Optional[str] = None) -> Dict[str, Any]:
        remote = remote or self.policy.default_remote
        branch = branch or self.policy.default_branch
        return self.run_cmd(f"git push {remote} {branch}", timeout_s=180)

    def grep_search(self, pattern: str, glob: str = "**/*") -> Dict[str, Any]:
        """Search for a pattern in files matching a glob."""
        try:
            cmd = f"grep -r --include={shlex.quote(glob)} {shlex.quote(pattern)} ."
            return self.run_cmd(cmd, timeout_s=120)
        except Exception as e:
            return {"error": str(e)}


def tool_schema() -> List[Dict[str, Any]]:
    return [
        {"type": "function", "function": {"name": "list_files", "parameters": {"type": "object", "properties": {"glob": {"type": "string"}, "max_items": {"type": "integer"}}}}},
        {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object", "properties": {"relpath": {"type": "string"}}, "required": ["relpath"]}}},
        {"type": "function", "function": {"name": "write_file", "parameters": {"type": "object", "properties": {"relpath": {"type": "string"}, "content": {"type": "string"}}, "required": ["relpath", "content"]}}},
        {"type": "function", "function": {"name": "run_cmd", "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}, "timeout_s": {"type": "integer"}}, "required": ["cmd"]}}},
        {"type": "function", "function": {"name": "grep_search", "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "glob": {"type": "string"}}, "required": ["pattern"]}}},
        {"type": "function", "function": {"name": "git_status", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "git_diff", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "git_stash", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "git_pop", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "git_commit", "parameters": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}}},
        {"type": "function", "function": {"name": "git_push", "parameters": {"type": "object", "properties": {"remote": {"type": "string"}, "branch": {"type": "string"}}}}},
        {"type": "function", "function": {"name": "request_permission", "parameters": {"type": "object", "properties": {"reason": {"type": "string"}, "cmd_pattern": {"type": "string"}}, "required": ["reason", "cmd_pattern"]}}},
    ]


def heuristic_extract_tool_calls(content: str) -> List[Dict[str, Any]]:
    """Fallback: extract tool calls from markdown code blocks if the model chats instead of calling tools."""
    calls = []
    
    # 1. Match function-style calls: tool_name(arg1='val', arg2=123)
    # This matches both inside and outside code blocks.
    fn_patterns = [
        r"(\w+)\(([\w\s,='\"./\-\*]*)\)",
    ]
    
    # Common tools to look for
    valid_tools = {
        "list_files", "read_file", "write_file", "run_cmd", "grep_search",
        "git_status", "git_diff", "git_stash", "git_pop", "git_commit", "git_push"
    }

    # 2. Match bash blocks as run_cmd (only if not a function call)
    bash_blocks = re.findall(r"```(?:bash|sh|shell)\n(.*?)\n```", content, re.DOTALL)
    for block in bash_blocks:
        clean_block = block.strip()
        # Check if it's a tool call like read_file(...)
        found_tool = False
        for tool in valid_tools:
            if clean_block.startswith(tool + "("):
                found_tool = True
                break
        
        if found_tool:
            # We'll let the general pattern handle this
            continue

        calls.append({
            "function": {
                "name": "run_cmd",
                "arguments": {"cmd": clean_block}
            }
        })
    
    # 3. Match python-style tool calls (simple regex)
    for tool in valid_tools:
        # Pattern for: tool_name(key='val', key2="val")
        pattern = rf"{tool}\((.*?)\)"
        matches = re.findall(pattern, content, re.DOTALL)
        for m in matches:
            # Simple argument parser for key='val' or key="val"
            args = {}
            arg_matches = re.findall(r"(\w+)\s*=\s*['\"](.*?)['\"]", m)
            for k, v in arg_matches:
                args[k] = v
            
            # Special case for run_cmd('ls')
            if not args and m.strip():
                raw = m.strip().strip("'").strip('"')
                if tool == "run_cmd":
                    args["cmd"] = raw
                elif tool == "read_file":
                    args["relpath"] = raw

            calls.append({
                "function": {
                    "name": "run_cmd" if tool == "run_cmd" else tool,
                    "arguments": args
                }
            })
        
    return calls


def boot_sequence(repo_root: Path, role: str, tooling: Tooling) -> str:
    """Implements Procedure 009 'Reload Before Every Task' and work finding."""
    progress(f"Boot sequence for role={role}")
    
    context = ["# CORE MISSION DIRECTIVES"]
    
    # 1. Core Documentation (FIXED)
    context.append("## SYSTEM DOCUMENTATION")
    for doc in ["README.md", "AGENTS.md"]:
        p = repo_root / doc
        if p.exists():
            context.append(f"### FILE: {doc}")
            context.append(p.read_text(encoding='utf-8', errors='replace')[:5000])

    # 2. Identity (FIXED)
    role_path = repo_root / "roles" / f"{role}.md"
    if role_path.exists():
        context.append("## IDENTITY AND SCOPE")
        context.append(role_path.read_text(encoding='utf-8', errors='replace'))
    
    # 3. Operating Procedures (FIXED)
    context.append("## OPERATING PROCEDURES")
    for proc_num in ["001", "002", "004", "009", "017", "042"]:
        match = list(repo_root.glob(f"procedures/{proc_num}_PROCEDURE_*.md"))
        if match:
            p_file = match[0]
            context.append(f"### Procedure {proc_num}: {p_file.stem}")
            context.append(p_file.read_text(encoding='utf-8', errors='replace'))

    # 4. Work Queue
    today = time.strftime("%Y-%m-%d", time.gmtime())
    work_files: List[Path] = []
    
    comms = list(repo_root.glob(f"agents-comms/{today}_*2{role}.md"))
    work_files.extend(comms)
    
    for wip_f in repo_root.glob("wip/*.md"):
        content = wip_f.read_text(encoding="utf-8", errors="replace")
        if role.lower() in content.lower():
            work_files.append(wip_f)
            
    for todo_f in repo_root.glob("todos/*.md"):
        content = todo_f.read_text(encoding="utf-8", errors="replace")
        if role.lower() in content.lower():
            blocked = False
            for line in content.splitlines():
                if "blocked by:" in line.lower() and not any(x in line.lower() for x in ["none", "n/a"]):
                    blocked = True
                    break
            if not blocked:
                work_files.append(todo_f)

    if not work_files:
        progress(f"No active work found for role={role}. Writing IDLE state.")
        session_file = repo_root / "sessions" / f"{today}_SESSION_STATE.md"
        if not session_file.exists():
            template = (f"# Session State — {today}\n\n## Status: CLOSED\n\n## End of Session Summary\nRole {role} invoked, no work found. Exiting IDLE.\n")
            session_file.parent.mkdir(parents=True, exist_ok=True)
            session_file.write_text(template, encoding="utf-8")
        # In chat mode, we still return the manifest documentation even if no work
        return "\n\n".join(context)

    work_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    
    context.append("## ACTIVE WORK QUEUE")
    for wf in work_files[:5]:
        rel = str(wf.relative_to(repo_root))
        context.append(f"### WORK_FILE: {rel}")
        context.append(wf.read_text(encoding='utf-8', errors='replace'))
        
    return "\n\n".join(context)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--role", required=True)
    ap.add_argument("--model", required=False)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--budget", default="0")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--max-steps", type=int, default=40)
    ap.add_argument("--allow-unsafe-cmds", action="store_true")
    ap.add_argument("--policy", default="policy.yaml")
    args = ap.parse_args()

    repo_root = Path(args.repo).resolve()
    policy_path = repo_root / "src" / args.policy
    audit_path = Path("/var/log/jax/jax_audit.jsonl")

    policy = Policy.from_file(policy_path, repo_root, allow_unsafe_cmds=args.allow_unsafe_cmds)
    tooling = Tooling(policy, audit_path)
    client = OllamaClient(policy.ollama_base_url)

    model = args.model or policy.__dict__.get("default_model", "qwen3-coder:latest")

    # 1. Preflight check
    progress(f"Starting JAX headless runner for role={args.role} model={model}")
    progress("Running preflight check...")
    if not client.preflight(model):
        eprint(f"[{now_iso()}] FATAL: Model '{model}' not found in Ollama at {client.base_url}")
        return 1
    progress("Preflight OK.")

    # 2. Boot sequence
    boot_context = boot_sequence(repo_root, args.role, tooling)
    
    # Only exit early if NO work found AND the prompt is the default 'look for work' one.
    is_generic = "look for work" in args.prompt.lower() or "find work" in args.prompt.lower()
    if not boot_context and is_generic:
        progress("No work found for generic prompt. Exiting 0.")
        return 0

    tools = tool_schema()

    system = load_system_prompt(repo_root, args.role, mode="headless", tools=DEFAULT_TOOLS)

    if "deepseek-coder" in model.lower():
        system += "\n\n### TOOL CALLING FORMAT FOR DEEPSEEK\n"
        system += "You MUST call tools using the following markdown format if native tool calling is unavailable:\n"
        system += "```bash\nlist_files(glob='**/*.py')\n```\n"
        system += "Or use the standard function call within a bash block:\n"
        system += "```bash\nread_file(relpath='README.md')\n```\n"

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"### START MISSION\n\n{boot_context}\n\n### INITIAL TASK\n{args.prompt}\n\nAnalyze the CORE MISSION DIRECTIVES above and execute the INITIAL TASK. Confirm your identity and mission focus first."},
    ]

    progress("Entering agent loop.")
    start = time.time()
    for step in range(1, args.max_steps + 1):
        if time.time() - start > args.timeout - 10:
            progress(f"TIMEOUT: reached for role={args.role}")
            return 124

        progress(f"Step {step}: Model call...")
        try:
            resp = client.chat(model=model, messages=messages, tools=tools)
            if "error" in resp:
                progress(f"FATAL: {resp['error']}")
                return 1
        except Exception as e:
            eprint(f"[{now_iso()}] ERROR: Ollama chat call failed: {e}")
            return 2

        msg = resp.get("message") or {}
        messages.append(msg)

        content = (msg.get("content") or "").strip()
        tool_calls = msg.get("tool_calls") or []

        if content:
            print(content, flush=True)

        if not tool_calls:
            # Try heuristic extraction
            tool_calls = heuristic_extract_tool_calls(content)
            if tool_calls:
                progress(f"Heuristic: extracted {len(tool_calls)} tool calls from content.")
            else:
                progress(f"DONE: role={args.role} model={model} steps={step}")
                return 0

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
                elif fn_name == "grep_search":
                    out = tooling.grep_search(pattern=str(fn_args["pattern"]), glob=str(fn_args.get("glob", "**/*")))
                elif fn_name == "git_status":
                    out = tooling.git_status()
                elif fn_name == "git_diff":
                    out = tooling.git_diff()
                elif fn_name == "git_stash":
                    out = tooling.git_stash()
                elif fn_name == "git_pop":
                    out = tooling.git_pop()
                elif fn_name == "git_commit":
                    out = tooling.git_commit(message=str(fn_args["message"]))
                elif fn_name == "git_push":
                    out = tooling.git_push(remote=fn_args.get("remote"), branch=fn_args.get("branch"))
                elif fn_name == "request_permission":
                    out = {"status": "PENDING_HUMAN_APPROVAL", "message": "Approval requested in chat."}
                else:
                    out = {"error": f"Unknown tool: {fn_name}"}
            except Exception as e:
                out = {"error": str(e)}

            if "error" in out or (isinstance(out, dict) and out.get("rc", 0) != 0):
                if "error" in out: progress(f"Tool error: {out['error']}")
                else: progress(f"Command failed with rc={out['rc']}")
                
            messages.append({"role": "tool", "name": fn_name, "content": json.dumps(out)})

    progress(f"STOP: max_steps reached for role={args.role}")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
