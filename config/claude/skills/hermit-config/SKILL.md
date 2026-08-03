# 三、配置注入机制（自动执行，Agent 无需干预）

容器 CMD 启动时会自动执行以下配置注入：

  1) 复制 /agent-config/* 到 ~/.claude/（跳过 /agent-config/workspace）
  2) 启动 SSH 服务（端口 22）
  3) 生成 ~/.claude/settings.json，设置 trustedProjects、hasCompletedOnboarding 等字段
  4) 如果存在 user_start.sh，执行它并后台运行
  5) 如果是 ollama 类型，启动 ollama serve 并拉取 OLLAMA_MODEL 模型
