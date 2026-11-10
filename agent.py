#!/usr/bin/env python3
"""AI security agent - Groq LLM, runs in GitHub Actions, reports via Telegram"""
import os, sys, json, requests, subprocess
from openai import OpenAI

TG_TOKEN = os.environ["TG_TOKEN"]
CHAT_ID  = os.environ["CHAT_ID"]

client = OpenAI(
    api_key=os.environ["GROQ_API_KEY"],
    base_url="https://api.groq.com/openai/v1",
)
MODEL = "groq/openai/gpt-oss-120b"   # Groq ရဲ့ fast 70B


def tg_send(text: str):
    for i in range(0, len(text), 3900):
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text[i:i + 3900]}, timeout=30)


def run_cmd(cmd: str, timeout: int = 300) -> str:
    ALLOWED = ("nmap", "whatweb", "dig", "whois", "curl",
               "nuclei", "httpx", "ping", "ls", "cat")
    if not cmd.strip().split() or cmd.strip().split()[0] not in ALLOWED:
        return "BLOCKED: command not allowed"
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return ((r.stdout + r.stderr) or "(no output)")[-3500:]
    except subprocess.TimeoutExpired:
        return "TIMEOUT"


def save_finding(text: str) -> str:
    with open("findings.md", "a") as f:
        f.write(f"## {text}\n\n")
    return "saved"


TOOLS = {"run_cmd": run_cmd, "save_finding": save_finding}

TOOL_SCHEMA = [
    {"type": "function",
     "function": {
         "name": "run_cmd",
         "description": "Run an allowed recon command (nmap, curl, dig, whatweb, nuclei, httpx...)",
         "parameters": {"type": "object",
                        "properties": {"cmd": {"type": "string"},
                                       "timeout": {"type": "integer", "default": 300}},
                        "required": ["cmd"]}}},
    {"type": "function",
     "function": {
         "name": "save_finding",
         "description": "Save an important finding",
         "parameters": {"type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"]}}},
]

SYSTEM = """You are an authorized security-testing agent. Plan the task step by step,
use tools to gather data, save important findings with save_finding, then output
a concise final report. Stay within the user-declared target only."""


def agent_loop(goal: str, max_turns: int = 12):
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": goal}]
    for turn in range(max_turns):
        resp = client.chat.completions.create(
            model=MODEL, messages=messages, tools=TOOL_SCHEMA,
            max_tokens=4096, temperature=0.2)
        msg = resp.choices[0].message

        if not msg.tool_calls:
            tg_send(msg.content or "(no output)")   # final report → Telegram
            return

        messages.append(msg.model_dump())            # assistant msg with tool_calls
        for call in msg.tool_calls:
            name = call.function.name
            args = json.loads(call.function.arguments or "{}")
            print(f"[TURN {turn}] {name} {str(args)[:120]}")
            out = TOOLS[name](**args)
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": out[:3500]})
    tg_send("⚠️ max_turns ပြည့်သွားပါတယ် — goal မပြီးဆုံးပါ။")


if __name__ == "__main__":
    goal = " ".join(sys.argv[1:])
    try:
        agent_loop(goal)
    except Exception as e:
        tg_send(f"❌ Agent error: {e}")
        raise
