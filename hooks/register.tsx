import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

// 回复原文 → Gemini 解读。换了存法就改 shape 的标签，旧数据会被当成空的
const explained = atom(
  { plugin: 'explain-claude', key: 'explained' } as const,
  {} as Record<string, string>,
  { shape: 'explained-1' },
)
const showOriginal = atom({ plugin: 'explain-claude', key: 'showOriginal' } as const, false)

const HEADER = '**【Gemini 解读】**\n\n'

// 同一段话在存档和屏幕上空白可能略有不同，比对前压掉空白
const keyOf = (text: string) => text.replace(/\s+/g, ' ').trim()

const str = (v: unknown, fallback: string) => (typeof v === 'string' && v.trim() ? v.trim() : fallback)
const num = (v: unknown, fallback: number) => {
  const n = typeof v === 'string' ? Number(v) : v
  return typeof n === 'number' && Number.isFinite(n) && n >= 0 ? n : fallback
}

export const register: Register = (on, options) => {
  const baseUrl = str(options.base_url, 'https://generativelanguage.googleapis.com/v1beta/openai')
  const model = str(options.model, 'gemini-3.1-pro-preview')
  const keyEnv = str(options.api_key_env, 'GEMINI_API_KEY')
  const minChars = num(options.min_chars, 400)
  const minToolCalls = num(options.min_tool_calls, 6)
  const keyEnvOk = /^[A-Za-z_][A-Za-z0-9_]*$/.test(keyEnv)

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'gemini',
      description: '在 Gemini 解读和 Claude 原文之间切换',
    })
    return next(e)
  })

  on('command.run', { command: 'gemini' }, async $ => {
    const now = await update($, showOriginal, v => !v)
    return { text: now ? '已切回 Claude 原文。' : '已切到 Gemini 解读。' }
  })

  // 每轮结束：只管主对话，不管子任务。放到定时器里跑，不拖住这一轮的收尾
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (e.agentId || e.reason !== 'answer') return result
    if (e.answer.replace(/\s/g, '').length < minChars) return result

    $.clock.after(1500, async () => {
      $.ui.status('Gemini 正在解读这一轮…')
      try {
        const { transcriptPath } = await $.session.info()
        if (!keyEnvOk) throw new Error(`密钥变量名 ${keyEnv} 不合法`)
        // 桌面 app 启动的会话不一定带着 shell 配置文件里的变量，所以经交互式 shell 启动脚本，
        // 让它先加载 ~/.zshrc 之类的文件，脚本再按变量名去读密钥
        const shell = (await $.env.get('SHELL')) || '/bin/zsh'
        const run = await $.process.run(
          [
            shell,
            '-ic',
            'exec /usr/bin/env python3 -I "$0" "$1"',
            `${$.plugin.root}/scripts/explain_turn.py`,
            transcriptPath,
          ],
          {
            env: {
              EXPLAIN_CLAUDE_BASE_URL: baseUrl,
              EXPLAIN_CLAUDE_MODEL: model,
              EXPLAIN_CLAUDE_API_KEY_ENV: keyEnv,
              EXPLAIN_CLAUDE_MIN_TOOL_CALLS: String(minToolCalls),
            },
            timeoutMs: 300_000,
          },
        )
        if (run.exitCode !== 0) throw new Error(run.stderr.slice(-300))
        // shell 配置文件可能往屏幕上打印东西，脚本的结果在最后一行
        const lastLine = run.stdout.trim().split('\n').pop() ?? ''
        const out = JSON.parse(lastLine) as
          | { skip: true }
          | { original: string; explained: string }
        // 工具调用太少（多半是闲聊），脚本没去调模型，原文不动
        if ('skip' in out) {
          $.ui.status(undefined)
          return
        }
        const { original, explained: text } = out
        await update($, explained, map => {
          const merged = { ...map, [keyOf(e.answer)]: text, [keyOf(original)]: text }
          // 只留最近 200 条，免得越存越大
          return Object.fromEntries(Object.entries(merged).slice(-200))
        })
        $.ui.status(undefined)
      } catch (err) {
        $.ui.status(undefined)
        $.ui.toast(`Gemini 解读失败：${String(err).slice(0, 200)}`)
      }
    })
    return result
  })

  // 画回复时：有解读就把显示的文字换掉。只改屏幕上的样子，存档和 Claude 读到的上下文都不变
  on('ui.render', { component: 'AssistantMessage' }, async ($, e, next) => {
    if (e.props.isSummary) return next(e)
    if (await read($, showOriginal)) return next(e)
    const text = (await read($, explained))[keyOf(e.props.text)]
    if (!text) return next(e)
    return next({ ...e, props: { ...e.props, text: HEADER + text } })
  })
}
