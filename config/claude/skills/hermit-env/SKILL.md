# 八、Claude Code 环境变量

容器内已预设以下 Claude Code 相关环境变量：

  CLAUDE_CODE_TRUST_ALL=true
  CLAUDE_CODE_SKIP_ONBOARDING=true
  CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

ollama 类型额外预设：
  ANTHROPIC_BASE_URL=http://192.168.0.209:11435
  ANTHROPIC_AUTH_TOKEN=ollama
  OLLAMA_MODEL=qwen3.5

claude 类型可在 /agent-config/settings.json 和 config.json 中配置：
  settings.json 的 env 字段
  config.json 的 providers[].settingsConfig.env.ANTHROPIC_AUTH_TOKEN
