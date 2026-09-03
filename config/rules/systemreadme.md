================================================================================
                     Hermit-Claw 容器内使用规范 / System Conventions
                              目标用户：容器内的 Agent
================================================================================

本文档包含 Hermit-Claw 平台最核心的两个功能（run_claude.js + /ask/claude 接口）。
其他规范已拆分为独立 skill（见下方索引），Agent 按需查阅以节省上下文。
所有 skill 位于 /agent-config/skills/ 目录下。

================================================================================
核心一、run_claude.js — 在 server.js 中调用 Claude
================================================================================

所有对 Claude 的调用必须通过 run_claude.js，不要直接调 claude CLI。
这样问题和 AI 回答才会统一记录到 logs/agent_tui.log。

### 调用方式（从 server.js 中的 spawn）

```javascript
const { spawn } = require('child_process');
const WORKSPACE_DIR = '/home/agent/.claude/workspace/project';

// 将消息 base64 编码
const msgB64 = Buffer.from(fullMessage).toString('base64');

const child = spawn('node', [path.join(WORKSPACE_DIR, 'run_claude.js')], {
    cwd: WORKSPACE_DIR,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: {
        ...process.env,
        ANTHROPIC_DISABLE_PREFLIGHT: '1',   // 跳过预检
        CLAUDE_CAPTURE_STDIO: '1',           // 捕获输出
        CLAUDE_MSG: msgB64,                  // base64 编码的消息
        // CLAUDE_IMG: '1',                  // [可选] 触发图文模式
    }
});

let stdout = '';
let stderr = '';
child.stdout.on('data', (data) => { stdout += data.toString(); });
child.stderr.on('data', (data) => { stderr += data.toString(); });
child.on('close', (code) => {
    if (code === 0) {
        res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
        res.end(stdout.trim());
    } else {
        res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
        res.end(stderr || `Exit code: ${code}`);
    }
});
```

### 图文模式（设置 CLAUDE_IMG=1）

当需要让 Claude 分析图片时：
1. 将图片写入 /home/agent/.claude/workspace/project/tmp.png
2. 设置 CLAUDE_IMG=1（任意非空值）
3. run_claude.js 会自动追加图片引用到消息中
4. 不设置 CLAUDE_IMG 时按纯文本模式处理

### 环境变量总结

| 变量 | 必须 | 说明 |
|------|------|------|
| ANTHROPIC_DISABLE_PREFLIGHT | 是 | 跳过启动预检，设为 '1' |
| CLAUDE_CAPTURE_STDIO | 是 | 捕获 Claude 输出，设为 '1' |
| CLAUDE_MSG | 是 | base64 编码的完整消息 |
| CLAUDE_IMG | 否 | 设为 '1' 触发图文模式 |

每次调用前会自动执行 claude --reset 清理会话缓存。
run_claude.js 使用 --dangerously-skip-permissions --continue --print 标志运行。

================================================================================
核心二、/ask/claude 接口 — 每个容器必备的 HTTP 服务
================================================================================

每个 claude agent 容器都要有一个 server.js 服务，监听端口 8082。

### 端点规范

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/ask/claude?q=...` | 向 Claude 提问，返回纯文本 |
| GET | `/health` | 健康检查 |

### 智能编码识别

- 参数包含空格 或 长度 < 50 → `decodeURIComponent(q)` 解码
- 其他情况 → base64 解码

### curl 示例

```bash
# 普通字符串（自动识别）
curl "http://localhost:8082/ask/claude?q=你好，请介绍一下自己"

# base64 编码（用于复杂内容）
curl "http://localhost:8082/ask/claude?q=$(echo '你好，请介绍一下自己' | base64)"
```

### 响应格式

- 成功：纯文本响应（200）
- 失败：错误信息（500）

================================================================================
核心三、注册到 Hub — Tools 知识库（19081）
================================================================================

Hub（19081）是平台统一的工具知识库与对接入口。tools 下的每个项目（如 obs 图床、
email 邮件等）都可把「自己是谁、提供哪些接口、怎么调用」注册到 Hub，展示在首页。

### 首页

http://dimond.top:19081 首页为「工具知识库」：底部 pills 切换工具、iframe 预览
工具 Web UI、Docs 查看器查看工具文档，并内置 Hub 公共接口文档与示例工具（obs）范本。

### 注册（公共接口规范）

推荐传「完整记录」（`name` 必填，`doc_md` 写清所有功能性接口）：

```json
{
  "name": "obs",
  "display_name": "OBS 图床",
  "description": "文件托管、断点续传、公告板服务",
  "port": 19082,
  "doc_md": "# OBS 图床 ...（功能接口 Markdown）"
}
```

也可传「简化记录」（`container_name` 必填），Hub 自动派生 name / port / doc_md：

```json
{
  "container_name": "19082-writer",
  "host_port": 19082,
  "agent_type": "claude",
  "description": "写作工具，提供 /ask/claude 接口"
}
```

### 查询 / 注销

```
GET     http://host.docker.internal:19081/api/tools           # 全部
GET     http://host.docker.internal:19081/api/tools/<name>    # 单个
DELETE  http://host.docker.internal:19081/api/tools/<name>    # 注销
```

### 调用约定

容器卡片之间的调用统一走宿主机端口：`http://dimond.top:19xxx`（xxx 为该工具分配的端口）。

更多细节（响应字段、持久化位置）见 skill：hermit-tools-hub。

================================================================================
其他规范索引（按需查阅 /agent-config/skills/）
================================================================================

| 编号 | 规范名称 | Skill | 说明 |
|------|---------|-------|------|
| 一 | 容器内固定路径 | hermit-paths | 工作目录、日志目录、启动脚本、配置挂载路径 |
| 二 | 日志规范 | hermit-logging | start.log / agent_tui.log / run.log / ollama.log |
| 三 | 配置注入机制 | hermit-config | 容器启动时自动执行的配置注入流程 |
| 四 | Agent 类型差异 | hermit-agent-types | claude / ollama / openclaw 路径差异 |
| 五 | 服务端口 | hermit-ports | 8082 内部端口、19081-19999 宿主机端口规范 |
| 六 | 容器用户身份 | hermit-user | agent (uid=501) 用户与 sudo 权限 |
| 七 | 初始化消息 | hermit-init | Agent 新会话收到的初始指令 |
| 八 | 环境变量 | hermit-env | CLAUDE_CODE_* 环境变量与 API 配置 |
| 十一 | Git 管理规范 | hermit-git | 每次对话后提交、commit.txt、.gitignore |
| 十二 | 推荐工作流 | hermit-workflow | 开发→调试→更新 README→总结会话 |
| 十三 | Supabase 数据库 | hermit-supabase | 安装方法、连接池地址、客户端示例 |
| 十五 | Tools 知识库接口 | hermit-tools-hub | 19081 Hub 对接文档首页、容器卡片可选注册 |

首次启动时应至少查阅 hermit-paths、hermit-ports、hermit-workflow。
