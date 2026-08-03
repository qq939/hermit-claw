# 二、日志规范

1. 启动日志（user_start.sh 输出）
   /home/agent/.claude/workspace/project/logs/start.log

   容器启动时自动执行 user_start.sh，日志追加写入 start.log。

2. Claude Code / Claude TUI 会话日志
   /home/agent/.claude/workspace/project/logs/agent_tui.log

   Claude Code 运行时的 TUI 日志文件。
   宿主机控制面板通过 cat 命令读取此文件用于日志下载。

3. 服务运行日志（web app 运行时）
   /home/agent/.claude/workspace/project/logs/run.log

   服务端的日志输出。

4. Ollama 服务日志（仅 ollama agent 类型）
   /home/agent/.claude/workspace/project/logs/ollama.log

   Ollama 服务端的日志输出。
