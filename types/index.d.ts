declare module 'claude-code' {
  interface PluginState {
    'explain-claude': {
      // 回复原文（压掉空白后）→ Gemini 的解读
      explained: Shaped<Record<string, string>>
      // true 时显示原文，/gemini 切换
      showOriginal: boolean
    }
  }
}
