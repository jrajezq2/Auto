#!/usr/bin/env python3
import os, json, subprocess
import telebot
from litellm import completion

# Telegram Bot Token နှင့် Groq API Key များကို Environment Variables မှ ယူပါမည်
TG_TOKEN = os.environ.get("TG_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# မင်းသုံးခွင့်ရှိတဲ့ Model Name
MODEL = "groq/openai/gpt-oss-120b"

bot = telebot.TeleBot(TG_TOKEN)

def run_cmd(cmd: str, timeout: int = 300) -> str:
    ALLOWED = ("nmap", "whatweb", "dig", "whois", "curl", "nuclei", "httpx", "ping", "ls", "cat")
    parts = cmd.strip().split()
    if not parts or parts[0] not in ALLOWED:
        return "BLOCKED: command not allowed"
    try:
        r = subprocess.run(parts, capture_output=True, text=True, timeout=timeout)
        return ((r.stdout + r.stderr) or "(no output)")[-3500:]
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    except Exception as e:
        return f"ERROR: {e}"

def save_finding(text: str) -> str:
    with open("findings.md", "a", encoding="utf-8") as f:
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
         "description": "Save an important finding to report file",
         "parameters": {"type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"]}}},
]

SYSTEM = """You are an authorized security-testing agent. Plan the task step by step,
use tools to gather data, save ALL important findings using save_finding tool. 
At the end, say 'Finished'."""

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "🛡️ Security Agent မှ ကြိုဆိုပါတယ်။\nစစ်ဆေးလိုသော Target URL သို့မဟုတ် IP ကို ပို့ပေးပါ။")

@bot.message_handler(func=lambda message: True)
def handle_target(message):
    target = message.text.strip()
    status_msg = bot.reply_to(message, f"🔍 စတင်စစ်ဆေးနေပါပြီ...\nTarget: `{target}`\nအချိန်အနည်းငယ် စောင့်ပေးပါ။", parse_mode="Markdown")

    # ယခင် Report ဖိုင်ဟောင်းရှိပါက ဖျက်ပါ
    if os.path.exists("findings.md"):
        os.remove("findings.md")

    # Agent Loop စတင်ခြင်း
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Scan this target: {target}"}]
    
    max_turns = 12

    try:
        for turn in range(max_turns):
            resp = completion(
                model=MODEL, 
                messages=messages, 
                tools=TOOL_SCHEMA,
                max_tokens=4096, 
                temperature=0.2,
                api_key=GROQ_API_KEY
            )
            
            msg = resp.choices[0].message
            msg_dict = msg.model_dump(exclude_none=True) if hasattr(msg, "model_dump") else dict(msg)
            calls = msg_dict.get("tool_calls") or []
            
            if not calls:
                # Tool ဆက်မသုံးတော့ရင် Loop ထဲကထွက်ပါမယ်
                break

            messages.append(msg_dict)
            
            for call in calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                args = json.loads(fn.get("arguments") or "{}")
                
                print(f"[TURN {turn}] Run: {name}")
                out = TOOLS[name](**args) if name in TOOLS else "Error: Tool not found"
                
                messages.append({
                    "role": "tool", 
                    "tool_call_id": call.get("id", ""),
                    "name": name,
                    "content": out[:3500]
                })

        # Report ဖိုင်ကို Telegram သို့ Document အဖြစ် ပို့ပါမယ်
        if os.path.exists("findings.md"):
            with open("findings.md", "rb") as report_file:
                bot.send_document(
                    message.chat.id, 
                    report_file, 
                    caption="✅ စစ်ဆေးမှု ပြီးဆုံးပါပြီ။ ရလဒ်ကို ဖိုင်ထဲတွင် ကြည့်ရှုနိုင်ပါသည်။"
                )
        else:
            bot.send_message(message.chat.id, "✅ စစ်ဆေးမှု ပြီးဆုံးပါပြီ။ (အရေးကြီးသော တွေ့ရှိချက် မရှိပါ / မှတ်တမ်းမတင်ခဲ့ပါ)")

    except Exception as e:
        bot.reply_to(message, f"❌ အမှားအယွင်းဖြစ်ပေါ်ခဲ့ပါသည်: {e}")

if __name__ == "__main__":
    print("Bot is listening for commands from Telegram...")
    bot.infinity_polling()
