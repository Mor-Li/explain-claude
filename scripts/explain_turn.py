"""把 Claude Code 最近一轮的完整轨迹交给 Gemini（或任何 OpenAI 兼容接口的模型），换成大白话解读。

配置都从环境变量读，插件会按安装时填的选项替你设好：
    EXPLAIN_CLAUDE_BASE_URL       OpenAI 兼容接口地址，默认 Google 的 Gemini 接口
    EXPLAIN_CLAUDE_MODEL          模型名
    EXPLAIN_CLAUDE_API_KEY_ENV    密钥放在哪个环境变量里，默认 GEMINI_API_KEY
    EXPLAIN_CLAUDE_API_KEY        也可以直接给密钥，优先用它
    EXPLAIN_CLAUDE_MIN_TOOL_CALLS 一轮至少调多少次工具才解读
    EXPLAIN_CLAUDE_HISTORY_DIR    存档放哪，默认 ~/.config/explain-claude/history
prompt 读仓库根目录的 prompt.md。同一位置有 prompt.local.md 就优先用它，
这个文件不进 git，放你自己的版本。

mod 每轮结束时调用它：
    python3 explain_turn.py <transcript.jsonl>
输出一行 JSON：{"original": 这一轮最后一段回复原文, "explained": Gemini 的解读}
每次解读成功都存一份档：一个 JSON 文件，里面有发给模型的全文、Claude 原文和解读。只增不删。
下面几种试跑命令都不存档。

单独试跑（只打印，不影响任何东西）：
    python3 explain_turn.py <transcript.jsonl> --print            # 解读最近一轮
    python3 explain_turn.py <transcript.jsonl> --print --back 1   # 解读上一轮，以此类推
    python3 explain_turn.py <transcript.jsonl> --show             # 只打印要发给 Gemini 的全文，不调用

固定一轮反复调 prompt：
    python3 explain_turn.py <transcript.jsonl> --back 1 --dump samples/xxx.txt   # 把那一轮的轨迹存成文件
    python3 explain_turn.py --sample samples/xxx.txt                            # 用现在的 prompt 拿它问一次 Gemini，只打印
"""

import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_prompt():
    """prompt.local.md 优先，没有就用 prompt.md。{trajectory} 会被换成这一轮的轨迹。"""
    for name in ("prompt.local.md", "prompt.md"):
        path = os.path.join(ROOT, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
    raise FileNotFoundError("找不到 prompt.md")


BASE_URL = os.environ.get("EXPLAIN_CLAUDE_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai").rstrip("/")
MODEL = os.environ.get("EXPLAIN_CLAUDE_MODEL", "gemini-4-argon")
CLIP = 2000  # 每个工具输入或返回最多留多少字，太长的截断
# 这一轮工具调用不到这么多次就不解读（纯聊天的轮次一次都没有）
MIN_TOOL_CALLS = int(os.environ.get("EXPLAIN_CLAUDE_MIN_TOOL_CALLS", "6"))
HISTORY_DIR = os.path.expanduser(
    os.environ.get("EXPLAIN_CLAUDE_HISTORY_DIR", "~/.config/explain-claude/history")
)
# 这些是 Claude 给 app 更新任务列表、写收尾小结用的，闲聊时也会调，不算真干活
BOOKKEEPING_TOOLS = ("mcp__ccd_turn__",)


def clip(text, n=CLIP):
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    return text if len(text) <= n else text[:n] + f"…（后面还有 {len(text) - n} 字，截断）"


def is_real_prompt(row):
    """用户自己发的消息，而不是工具返回或系统插进来的内容。"""
    if row.get("type") != "user" or row.get("isMeta"):
        return False
    content = row.get("message", {}).get("content")
    if isinstance(content, str):
        return True
    return isinstance(content, list) and any(b.get("type") in ("text", "image") for b in content)


def is_command_row(row):
    """敲 /gemini 这类斜杠命令留下的记录，不算一轮的开头。"""
    content = row.get("message", {}).get("content")
    text = content if isinstance(content, str) else " ".join(b.get("text", "") for b in content or [])
    return text.lstrip().startswith(("<command-name>", "<local-command"))


def last_turn(path, back=0):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    rows = [r for r in rows if r.get("type") in ("user", "assistant")]
    starts = [i for i, r in enumerate(rows) if is_real_prompt(r) and not is_command_row(r)] or [0]
    starts.append(len(rows))
    k = max(0, len(starts) - 2 - back)
    return rows[starts[k]:starts[k + 1]]


def count_tool_calls(turn):
    return sum(
        1
        for row in turn if row.get("type") == "assistant"
        for b in row.get("message", {}).get("content") or []
        if isinstance(b, dict) and b.get("type") == "tool_use"
        and not str(b.get("name", "")).startswith(BOOKKEEPING_TOOLS)
    )


def render(turn):
    parts = ["（下面是 Claude 跟用户最近一轮的记录。读这段解读的就是这位用户本人，解读里用“你”称呼用户，用“我”指 Claude。）"]
    final_text = ""
    for row in turn:
        content = row.get("message", {}).get("content")
        if isinstance(content, str):
            parts.append(f"【用户问】\n{content}")
            continue
        for b in content or []:
            t = b.get("type")
            if t == "text":
                who = "用户问" if row["type"] == "user" else "Claude 回复"
                parts.append(f"【{who}】\n{b['text']}")
                if row["type"] == "assistant":
                    final_text = b["text"]
            elif t == "image":
                parts.append("【用户问】（发了一张截图）")
            elif t == "thinking" and b.get("thinking"):
                parts.append(f"【Claude 心里想】\n{clip(b['thinking'])}")
            elif t == "tool_use":
                parts.append(f"【Claude 调工具 {b.get('name')}】\n{clip(b.get('input'))}")
            elif t == "tool_result":
                body = b.get("content")
                if isinstance(body, list):
                    body = "\n".join(x.get("text", "") for x in body if x.get("type") == "text")
                parts.append(f"【工具返回】\n{clip(body or '')}")
    return "\n\n".join(parts), final_text


def api_key():
    key = os.environ.get("EXPLAIN_CLAUDE_API_KEY") or os.environ.get(
        os.environ.get("EXPLAIN_CLAUDE_API_KEY_ENV", "GEMINI_API_KEY"), ""
    )
    if not key:
        raise SystemExit("没找到密钥：设 GEMINI_API_KEY，或用 EXPLAIN_CLAUDE_API_KEY_ENV 指定别的变量名")
    return key


def ask_model(prompt):
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=json.dumps({
            "model": MODEL,
            "max_tokens": 32768,
            "messages": [{"role": "user", "content": prompt}],
        }).encode(),
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json",
        },
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=240) as resp:
                return json.load(resp)["choices"][0]["message"]["content"].strip()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt * 3)


def save_history(transcript, prompt, original, explained):
    """存一份档。文件名开头是时间，后面跟会话编号的前 8 位，按名字排序就是时间顺序。"""
    session = os.path.splitext(os.path.basename(transcript))[0]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    os.makedirs(HISTORY_DIR, exist_ok=True)
    path = os.path.join(HISTORY_DIR, f"{stamp}-{session[:8]}.json")
    record = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "session": session,
        "transcript": transcript,
        "cwd": os.getcwd(),
        "base_url": BASE_URL,
        "model": MODEL,
        "prompt": prompt,
        "original": original,
        "explained": explained,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)


def main():
    if "--sample" in sys.argv:
        with open(sys.argv[sys.argv.index("--sample") + 1], encoding="utf-8") as f:
            print(ask_model(load_prompt().replace("{trajectory}", f.read())))
        return
    back = int(sys.argv[sys.argv.index("--back") + 1]) if "--back" in sys.argv else 0
    turn = last_turn(sys.argv[1], back)
    if "--dump" in sys.argv:
        out = sys.argv[sys.argv.index("--dump") + 1]
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(render(turn)[0])
        print(f"已存：{out}（这一轮调了 {count_tool_calls(turn)} 次工具）")
        return
    calls = count_tool_calls(turn)
    if calls < MIN_TOOL_CALLS:
        if "--print" in sys.argv or "--show" in sys.argv:
            print(f"这一轮只调了 {calls} 次工具，不到 {MIN_TOOL_CALLS} 次，不解读。")
        else:
            print(json.dumps({"skip": True}))
        return
    trajectory, final_text = render(turn)
    if "--show" in sys.argv:
        print(load_prompt().replace("{trajectory}", trajectory))
        return
    prompt = load_prompt().replace("{trajectory}", trajectory)
    explained = ask_model(prompt)
    if "--print" in sys.argv:
        print(explained)
    else:
        try:
            save_history(sys.argv[1], prompt, final_text, explained)
        except OSError as err:  # 存档失败不耽误替换显示
            print(f"存档失败：{err}", file=sys.stderr)
        print(json.dumps({"original": final_text, "explained": explained}, ensure_ascii=False))


if __name__ == "__main__":
    main()
