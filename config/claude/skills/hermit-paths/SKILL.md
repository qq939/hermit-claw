# 一、容器内固定路径

1. 项目工作目录（你的主目录）
   /home/agent/.claude/workspace/project

   这是你的根工作目录，所有项目代码都放在这里。
   Dockerfile WORKDIR 已设置为该目录。

2. 日志目录
   /home/agent/.claude/workspace/project/logs

   所有日志文件输出到这里。
   请将 user_start.sh 的启动日志写入 logs/start.log。
   Claude Code / Claude TUI 的会话日志文件为 logs/agent_tui.log。
   请将 web app的运行日志写入 logs/run.log

3. 启动脚本（重要！）
   /home/agent/.claude/workspace/project/user_start.sh

   如果存在且非空，容器启动时会自动执行。
   你应该将项目的启动命令写入此文件：
     示例：
       #!/bin/bash
       cd /home/agent/.claude/workspace/project
       python3 app.py >> logs/start.log 2>&1

4. 宿主机配置（只读挂载，不可修改）
   /agent-config

   宿主机的 config/{agent_type}/ 目录挂载到容器内的 /agent-config。
   内容会复制到 ~/.claude/ 目录下（见配置注入机制 skill）。

   注意：/agent-config/workspace 目录会被自动跳过，不会覆盖容器内的
   项目目录。

5. 控制面板 SCP 推送的规则文件目录
   宿主机会通过 SSH/SCP 将 config/rules/ 下的所有文件推送到
   你的项目目录下。这个目录放置的是项目级的规则文件。
