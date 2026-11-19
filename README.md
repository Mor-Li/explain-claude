# explain-claude

Claude Code 干完一轮长活，汇报往往又长又啰嗦。这个插件在每轮结束后，把这一轮的完整轨迹交给 Gemini（或任何 OpenAI 兼容接口的模型），让它用大白话重讲一遍，然后**在屏幕上原地替换** Claude 最后那段回复。

A Claude Code plugin that hands each long turn's full trajectory to Gemini (or any OpenAI-compatible model) and replaces Claude's final reply on screen, in place, with a plain-language retelling.

## 它怎么工作

1. 一轮结束时，如果这一轮**调用工具至少 6 次**，并且 Claude **最后那段回复超过 400 字**（不算空白），就开始解读。闲聊的轮次几乎不调工具，会自动跳过。
2. 插件读这次会话的记录文件，取出最近一轮：用户的提问、Claude 调的每个工具、工具返回、最后的回复，拼成一段文本，接在 prompt 后面发给模型。
3. 模型回来后，屏幕上那段回复换成解读，开头标「**【Gemini 解读】**」。一般要等二三十秒。

只改屏幕上的显示，会话存档和 Claude 自己读到的上下文都不变。输入 `/gemini` 可以在解读和原文之间来回切换。

## 安装

在终端里的 Claude Code 会话中：

```
/plugin install explain-claude --marketplace Mor-Li/explain-claude
```

或者在 shell 里：

```bash
claude plugin install explain-claude --marketplace Mor-Li/explain-claude
```

在 Claude 桌面 app 里：点输入框旁边的 +，选 Plugins，Add marketplace 填 `Mor-Li/explain-claude`，再 Add plugin。

安装时会问是否添加这个插件市场，回答 `y`，然后选安装范围，再填下面几项设置。

## 设置

| 设置 | 默认值 | 说明 |
| --- | --- | --- |
| 接口地址 `base_url` | `https://generativelanguage.googleapis.com/v1beta/openai` | OpenAI 兼容接口的地址，不带 `/chat/completions`。默认是 Google Gemini 官方接口 |
| 模型名 `model` | `gemini-3.1-pro-preview` | 改成你的接口上能用的模型 |
| 密钥所在的环境变量名 `api_key_env` | `GEMINI_API_KEY` | 填变量的名字，不是密钥本身 |
| 最少字数 `min_chars` | `400` | 最后那段回复不到这么多字就不解读 |
| 最少工具调用次数 `min_tool_calls` | `6` | 这一轮工具调用不到这么多次就不解读 |

密钥只从环境变量读，不写进任何设置文件。从桌面 app 启动的会话如果读不到这个变量，插件会再让你的登录 shell 读一次，所以把 `export GEMINI_API_KEY=...` 写进 `~/.zshrc` 之类的文件就行。需要 `python3`，只用标准库。

## 改 prompt

发给模型的 prompt 在仓库根目录的 `prompt.md`，`{trajectory}` 会被换成这一轮的轨迹。

想用自己的版本，在同一位置建一个 `prompt.local.md`，插件会优先用它。这个文件在 `.gitignore` 里，不会被提交，适合放带个人称呼、个人口吻的 prompt。

调 prompt 时可以拿固定的一轮反复试，不用等真实对话：

```bash
# 把某个会话的上一轮存成样本（--back 0 是最近一轮，1 是上一轮）
python3 scripts/explain_turn.py ~/.claude/projects/<项目>/<会话>.jsonl --back 1 --dump samples/demo.txt

# 用现在的 prompt 拿样本问一次模型，只打印结果
python3 scripts/explain_turn.py --sample samples/demo.txt

# 只看要发给模型的全文，不调用
python3 scripts/explain_turn.py ~/.claude/projects/<项目>/<会话>.jsonl --show
```

命令行试跑时默认读 `GEMINI_API_KEY`，接口和模型用环境变量 `EXPLAIN_CLAUDE_BASE_URL`、`EXPLAIN_CLAUDE_MODEL` 指定，密钥放在别的变量里就用 `EXPLAIN_CLAUDE_API_KEY_ENV` 指定变量名。`samples/` 也在 `.gitignore` 里。

## 文件

- `hooks/register.tsx`：插件主体，挂在一轮结束和画回复这两个时刻，注册 `/gemini` 命令
- `scripts/explain_turn.py`：读会话记录、拼轨迹、调模型
- `prompt.md`：默认 prompt
- `types/index.d.ts`：插件保存的数据（解读结果、当前显示哪一版）的类型声明

## 许可证

MIT
