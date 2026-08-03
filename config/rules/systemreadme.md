================================================================================
                     Hermit-Claw 容器内使用规范 / System Conventions
                              目标用户：容器内的 Agent
================================================================================

本文档是 Hermit-Claw 平台规范的**目录索引**。完整内容已拆分为独立 skill，
Agent 应按需查阅对应 skill 文件以节省上下文。

所有 skill 位于 config/claude/skills/ 目录下，Agent 可通过读取 SKILL.md 查阅。

================================================================================
规范索引（按需查阅）
================================================================================

| 编号 | 规范名称 | Skill | 说明 |
|------|---------|-------|------|
| 一 | 容器内固定路径 | hermit-paths | 工作目录、日志目录、启动脚本、配置挂载路径 |
| 二 | 日志规范 | hermit-logging | start.log / agent_tui.log / run.log / ollama.log |
| 三 | 配置注入机制 | hermit-config | 容器启动时自动执行的配置注入流程 |
| 四 | Agent 类型差异 | hermit-agent-types | claude / ollama / openclaw 路径差异 |
| 五 | 服务端口 | hermit-ports | 8082 内部端口、18000-19999 宿主机端口规范 |
| 六 | 容器用户身份 | hermit-user | agent (uid=501) 用户与 sudo 权限 |
| 七 | 初始化消息 | hermit-init | Agent 新会话收到的初始指令 |
| 八 | 环境变量 | hermit-env | CLAUDE_CODE_* 环境变量与 API 配置 |
| 十 | 图文模式接口 | hermit-ask-image | run_claude.js + CLAUDE_IMG + tmp.png |
| 十一 | Git 管理规范 | hermit-git | 每次对话后提交、commit.txt、.gitignore |
| 十二 | 推荐工作流 | hermit-workflow | 开发→调试→更新 README→总结会话 |
| 十三 | Supabase 数据库 | hermit-supabase | 安装方法、连接池地址、客户端示例 |
| 十四 | Ask Server 服务 | hermit-ask-server | /ask/claude 端点实现 (server.js + run_claude.js) |
| 十五 | Tools 知识库接口 | hermit-tools-hub | 向 18081 Hub 注册/查询工具文档（POST/GET /api/tools） |

================================================================================
使用方式
================================================================================

Agent 通过读取对应的 skill 文件获取详细规范，例如：

  # 读取路径规范
  cat /agent-config/skills/hermit-paths/SKILL.md

  # 读取 Git 规范
  cat /agent-config/skills/hermit-git/SKILL.md

每条 skill 独立、自包含，不需要加载其他 skill 即可理解对应规范。
首次启动时应至少查阅 hermit-paths、hermit-ports、hermit-workflow。
