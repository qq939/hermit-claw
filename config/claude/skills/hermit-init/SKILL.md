# 七、初始化消息（Agent 收到的新会话指令）

每个新会话开始时，Agent 会收到以下指令：

  "你生来就是为了开发、看护、运维 web app 8082（端口号），web app
   8082 所在的目录是 /home/agent/.{agent}/workspace/project，如果
   project 文件夹有 web app，请查看启动脚本是否存在，
   /home/agent/.{agent}/workspace/project/user_start.sh。如果不存在
   启动脚本，请立即写好启动脚本 user_start.sh，输出日志到当前目录下的
   logs/start.log。最后完善 readme 和 SKILL.md 文件，并且整理日志文件
   logs/agent_tui.log 里的主要内容，梳理出项目构建的结构和细节，
   总结最后3轮对话的内容。"

工具类容器与普通容器的端口不再区分，统一由 Control 面板分配。
容器是否注册到 19081 Hub 由用户在面板卡片上勾选决定（注册即把调用指南写入 Hub docs），
容器启动时不再强制注册。详见 hermit-tools-hub skill。
