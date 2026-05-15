# Hermit-Claw System README

## 1. 日志目录

```
/home/agent/.claude/workspace/project/logs
```

所有日志文件输出到这里。

- 请将 `user_start.sh` 的启动日志写入 `logs/start.log`
- Claude Code / Claude TUI 的会话日志文件为 `logs/agent_tui.log`
- 请将 web app 的运行日志写入 `logs/run.log`

---

## 2. Supabase 集成指南

### 2.1 安装依赖

运行以下命令安装必需的依赖：

```bash
npm install @supabase/supabase-js @supabase/ssr
```

### 2.2 添加文件

#### 环境变量文件 `.env.local`

```
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_ixOQZXbObcNcP-PfiIrILg_PQtGKskp
```

#### 页面文件 `page.tsx`

```typescript
import { createClient } from '@/utils/supabase/server'
import { cookies } from 'next/headers'

export default async function Page() {
  const cookieStore = await cookies()
  const supabase = createClient(cookieStore)

  const { data: todos } = await supabase.from('todos').select()

  return (
    <ul>
      {todos?.map((todo) => (
        <li key={todo.id}>{todo.name}</li>
      ))}
    </ul>
  )
}
```

#### 服务器端客户端 `utils/supabase/server.ts`

```typescript
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

export const createClient = (cookieStore: Awaited<ReturnType<typeof cookies>>) => {
  return createServerClient(
    supabaseUrl!,
    supabaseKey!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll()
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) => cookieStore.set(name, value, options))
          } catch {
            // The `setAll` method was called from a Server Component.
            // This can be ignored if you have middleware refreshing
            // user sessions.
          }
        },
      },
    },
  );
};
```

#### 浏览器客户端 `utils/supabase/client.ts`

```typescript
import { createBrowserClient } from "@supabase/ssr";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

export const createClient = () =>
  createBrowserClient(
    supabaseUrl!,
    supabaseKey!,
  );
```

#### 中间件 `utils/supabase/middleware.ts`

```typescript
import { createServerClient } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

export const createClient = (request: NextRequest) => {
  let supabaseResponse = NextResponse.next({
    request: {
      headers: request.headers,
    },
  });

  const supabase = createServerClient(
    supabaseUrl!,
    supabaseKey!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll()
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) => request.cookies.set(name, value))
          supabaseResponse = NextResponse.next({
            request,
          })
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options)
          )
        },
      },
    },
  );

  return supabaseResponse
};
```

### 2.3 安装 Agent Skills（可选）

Agent Skills 为 AI 编码工具提供现成的指令、脚本和资源，以便更准确高效地使用 Supabase。

运行以下命令安装：

```bash
npx skills add supabase/agent-skills
```

### 2.4 Supabase 数据库连接池

使用以下连接字符串连接 Supabase 数据库连接池：

```
postgresql://postgres.uacwkmdyekxyqtopdele:Black_supabase00@aws-1-ap-northeast-2.pooler.supabase.com:5432/postgres
```

---

## 3. AI 对话助手功能指导

**重要：如果有 AI 助手，必须严格按照以下方案指导执行。**

### 3.1 Claude CLI 调用方法详解

本文档详细说明如何在 Node.js 服务器中调用 Claude CLI（claude 命令），实现与 AI 助手的交互，包括 API 密钥配置、进程管理、流式响应处理等。

#### 3.1.1 核心原理概述

Claude CLI 是 Anthropic 提供的命令行工具，通过 spawn 子进程方式调用。

主要特点：
- 使用子进程（child_process.spawn）启动 claude 命令
- 通过临时文件传递用户消息和上下文
- 支持 SSE（Server-Sent Events）流式响应
- 通过环境变量传递 API 密钥和配置

#### 3.1.2 API 密钥配置方法

Claude CLI 不直接接受密钥参数，而是通过环境变量读取配置。

必需的环境变量：
- `ANTHROPIC_AUTH_TOKEN`: API 密钥（格式：sk-xxxx...）
- `ANTHROPIC_API_KEY`: 同上，兼容另一种命名
- `ANTHROPIC_BASE_URL`: API 端点（默认 https://api.anthropic.com）
- `ANTHROPIC_MODEL`: 模型名称（可选，默认 claude-sonnet-4-20250514）
- `ANTHROPIC_DISABLE_PREFLIGHT`: 设为 '1' 跳过预检

示例配置：

```javascript
const env = {
  ANTHROPIC_AUTH_TOKEN: 'sk-xxxx...',           // API 密钥
  ANTHROPIC_BASE_URL: 'https://api.anthropic.com', // API 端点
  ANTHROPIC_DISABLE_PREFLIGHT: '1',              // 跳过预检
  PATH: process.env.PATH || '/usr/bin:/bin:/usr/local/bin'
};
```

从配置文件读取密钥：

```javascript
function getClaudeRuntimeEnv() {
  const result = {};
  const home = process.env.HOME || '';
  const configPaths = [
    home ? path.join(home, '.claude', 'config.json') : '',
    '/agent-config/config.json'
  ].filter(Boolean);

  for (const configPath of configPaths) {
    const config = readJsonFile(configPath);
    const current = config && config.claude && config.claude.current;
    const provider = current && config.claude.providers && config.claude.providers[current];
    const env = provider && provider.settingsConfig && provider.settingsConfig.env;
    if (env) Object.assign(result, env);
  }

  return result;
}
```

配置文件结构（~/.claude/config.json）：

```json
{
  "claude": {
    "current": "default",
    "providers": {
      "default": {
        "settingsConfig": {
          "env": {
            "ANTHROPIC_AUTH_TOKEN": "sk-xxxx...",
            "ANTHROPIC_BASE_URL": "https://api.anthropic.com"
          }
        }
      }
    }
  }
}
```

#### 3.1.3 启动 Claude CLI 进程

使用 child_process.spawn 启动 claude 命令：

```javascript
const { spawn } = require('child_process');

const args = [
  '--dangerously-skip-permissions',  // 跳过权限确认
  '--continue',                       // 继续之前的会话
  '-p',                               // print 模式（非交互）
  tmpFile                             // 临时文件路径（包含消息内容）
];

const claude = spawn('claude', args, {
  stdio: ['ignore', 'pipe', 'pipe'],  // 忽略 stdin，捕获 stdout 和 stderr
  env: env
});
```

关键参数说明：

| 参数                      | 说明                                   |
|--------------------------|----------------------------------------|
| --dangerously-skip-permissions | 跳过交互式权限确认（自动化必需）   |
| --continue               | 继续之前的会话上下文                   |
| -p / --print             | 打印输出模式（非 TUI 交互）             |
| -m / --model             | 指定模型（可选）                       |

#### 3.1.4 消息传递机制

**临时文件方式（推荐）**

将用户消息写入临时文件，通过 -p 参数传递：

```javascript
const tmpFile = TMPFILE_PATH + '.tmp.' + Date.now() + '.' + crypto.randomBytes(4).toString('hex');
fs.writeFileSync(tmpFile, tmpFileContent, 'utf8');
// args: ['--dangerously-skip-permissions', '--continue', '-p', tmpFile]
```

临时文件内容结构示例：

```
【用户问题】
用户的问题内容

---

【最近对话历史】
...

---

【技能提示词】
...

---

【文件提示词】
...
```

**Base64 编码方式**

使用 --print 配合 base64 编码直接传递消息：

```javascript
const encodedMsg = Buffer.from(message, 'utf8').toString('base64');
const args = [
  '--dangerously-skip-permissions',
  '--continue',
  '--print',
  encodedMsg
];
```

#### 3.1.5 流式响应处理（SSE）

监听 stdout 流：

```javascript
let stdout = '';
let stderr = '';

claude.stdout.on('data', (data) => {
  const chunk = data.toString();
  stdout += chunk;
  sendSSEMessage(res, 'chunk', chunk);  // 发送给客户端
});

claude.stderr.on('data', (data) => {
  const chunk = data.toString();
  stderr += chunk;
  // 日志记录 stderr 内容
});
```

SSE 消息格式：

```javascript
function sendSSEMessage(res, type, content) {
  res.write('data: ' + JSON.stringify({type: type, content: content}) + '\n\n');
}

// 消息类型：
// - 'chunk': 数据块
// - 'complete': 完成，携带 {dialogId, response}
// - 'error': 错误信息
```

#### 3.1.6 进程管理与错误处理

**超时处理**

```javascript
const TIMEOUT_MS = 1200000; // 20分钟

let killed = false;
let timeoutId = setTimeout(() => {
  if (!killed && claude && !claude.killed) {
    killed = true;
    claude.kill('SIGTERM');
    sendSSEMessage(res, 'error', '请求超时（1200秒），请重试');
    res.end();
  }
}, TIMEOUT_MS);
```

**进程关闭处理**

```javascript
claude.on('close', (code) => {
  clearTimeout(timeoutId);
  if (killed) return;
  killed = true;

  // 清理临时文件
  try { fs.unlinkSync(tmpFile); } catch(e) {}

  if (code === 0) {
    // 成功：保存响应
    dialog.aiResponse = stdout.trim();
    saveDialog(dialog);
    sendSSEMessage(res, 'complete', JSON.stringify({dialogId, response: stdout.trim()}));
  } else {
    // 失败：记录错误
    dialog.aiResponse = '（错误：' + (stderr || 'Claude进程退出，代码: ' + code) + '）';
    saveDialog(dialog);
    sendSSEMessage(res, 'error', 'Claude错误: ' + (stderr || '进程退出，代码: ' + code));
  }
  res.end();
});
```

**进程启动错误**

```javascript
claude.on('error', (err) => {
  clearTimeout(timeoutId);
  killed = true;
  logClaudeDebug('spawn:error', {error: err.message});
  try { fs.unlinkSync(tmpFile); } catch(e) {}
  sendSSEMessage(res, 'error', '启动Claude失败: ' + err.message);
  res.end();
});
```

#### 3.1.7 完整调用示例

```javascript
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

// 获取运行时环境变量（包含 API 密钥）
function getClaudeRuntimeEnv() {
  const result = {};
  const home = process.env.HOME || '';
  const configPath = path.join(home, '.claude', 'config.json');
  try {
    const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    const current = config?.claude?.current;
    const provider = config?.claude?.providers?.[current];
    const env = provider?.settingsConfig?.env;
    if (env) Object.assign(result, env);
  } catch (e) {}
  return result;
}

// 调用 Claude CLI
function callClaudeCLI(userMessage, res) {
  const tmpFile = '/tmp/claude_msg_' + Date.now() + '.txt';
  fs.writeFileSync(tmpFile, userMessage, 'utf8');

  const env = {
    ...process.env,
    ...getClaudeRuntimeEnv(),
    ANTHROPIC_DISABLE_PREFLIGHT: '1'
  };

  const claude = spawn('claude', [
    '--dangerously-skip-permissions',
    '--continue',
    '-p',
    tmpFile
  ], {
    stdio: ['ignore', 'pipe', 'pipe'],
    env: env
  });

  let stdout = '';
  let stderr = '';

  claude.stdout.on('data', (data) => {
    const chunk = data.toString();
    stdout += chunk;
    res.write('data: ' + JSON.stringify({type: 'chunk', content: chunk}) + '\n\n');
  });

  claude.stderr.on('data', (data) => {
    stderr += data.toString();
  });

  claude.on('close', (code) => {
    fs.unlinkSync(tmpFile);
    if (code === 0) {
      res.write('data: ' + JSON.stringify({type: 'complete', response: stdout.trim()}) + '\n\n');
    } else {
      res.write('data: ' + JSON.stringify({type: 'error', message: stderr}) + '\n\n');
    }
    res.end();
  });

  claude.on('error', (err) => {
    try { fs.unlinkSync(tmpFile); } catch(e) {}
    res.write('data: ' + JSON.stringify({type: 'error', message: err.message}) + '\n\n');
    res.end();
  });
}
```

#### 3.1.8 环境变量完整清单

| 变量名                      | 必需 | 说明                              |
|---------------------------|------|----------------------------------|
| ANTHROPIC_AUTH_TOKEN      | 是   | API 密钥，格式 sk-xxxx...        |
| ANTHROPIC_API_KEY         | 否   | API 密钥（别名）                  |
| ANTHROPIC_BASE_URL        | 否   | API 端点，默认 api.anthropic.com  |
| ANTHROPIC_MODEL           | 否   | 模型名称                          |
| ANTHROPIC_DISABLE_PREFLIGHT | 否 | 设为 '1' 跳过预检               |
| CLAUDE_CODE_TRUST_ALL     | 否   | 设为 'true' 信任所有项目          |
| CLAUDE_CODE_SKIP_ONBOARDING| 否  | 设为 'true' 跳过引导              |
| OLLAMA_MODEL              | 否   | Ollama 专用，指定模型             |

#### 3.1.9 Ollama 集成配置

如果使用本地 Ollama 服务：

```javascript
const env = {
  ANTHROPIC_BASE_URL: 'http://192.168.0.209:11435',
  ANTHROPIC_AUTH_TOKEN: 'ollama',      // Ollama 不需要真实密钥
  ANTHROPIC_MODEL: 'qwen3.5',          // 指定 Ollama 模型
  ANTHROPIC_DISABLE_PREFLIGHT: '1'
};
```

#### 3.1.10 调试技巧

1. 查看详细日志
   - 设置 logClaudeDebug 函数记录所有 spawn 相关事件
   - 记录 pid、args、env、elapsedMs、stdoutBytes 等

2. 常见错误排查
   - "启动失败"：检查 claude 命令是否存在
   - "请求超时"：检查网络连接或增加 TIMEOUT_MS
   - "API 错误"：检查 ANTHROPIC_AUTH_TOKEN 是否正确

3. 独立测试命令

   ```bash
   ANTHROPIC_AUTH_TOKEN=sk-xxxx... ANTHROPIC_DISABLE_PREFLIGHT=1 \
   claude --dangerously-skip-permissions --print "Hello"
   ```

---

## 3. Claude Ask Server 服务

每个 claude agent 卡片都要有一个初始的 server.js 服务，端口 8082，路径 `/ask/claude`，GET 访问，参数 `q="你要问的问题"`。支持 base64 编码，返回纯文本。底层依赖就是 `run_claude.js`。

### 3.1 server.js 实现

```javascript
const http = require('http');
const { spawn } = require('child_process');

const PORT = 8082;
const WORKSPACE_DIR = '/home/agent/.claude/workspace/project';

const server = http.createServer((req, res) => {
    const url = new URL(req.url, `http://localhost:${PORT}`);
    
    if (req.method === 'GET' && url.pathname === '/ask/claude') {
        const q = url.searchParams.get('q');
        
        if (!q) {
            res.writeHead(400, { 'Content-Type': 'text/plain; charset=utf-8' });
            res.end('Missing q parameter');
            return;
        }
        
        let question;
        try {
            question = Buffer.from(q, 'base64').toString('utf8');
        } catch (e) {
            res.writeHead(400, { 'Content-Type': 'text/plain; charset=utf-8' });
            res.end('Invalid base64 encoding');
            return;
        }
        
        const systemPrompt = 'You are a helpful assistant. Answer the question concisely. Do not use markdown or formatting.';
        const fullMessage = `${systemPrompt}\n\n${question}`;
        const msgB64 = Buffer.from(fullMessage).toString('base64');
        
        const child = spawn('claude', ['--dangerously-skip-permissions', '--continue', '-p', '/dev/stdin'], {
            cwd: WORKSPACE_DIR,
            stdio: ['pipe', 'pipe', 'pipe'],
            shell: true,
            env: { ...process.env, ANTHROPIC_DISABLE_PREFLIGHT: '1' }
        });
        
        let stdout = '';
        let stderr = '';
        
        child.stdout.on('data', (data) => {
            stdout += data.toString();
        });
        
        child.stderr.on('data', (data) => {
            stderr += data.toString();
        });
        
        child.on('close', (code) => {
            if (code === 0) {
                res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
                res.end(stdout.trim());
            } else {
                res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
                res.end(stderr || `Exit code: ${code}`);
            }
        });
        
        child.on('error', (err) => {
            res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
            res.end(`Spawn error: ${err.message}`);
        });
        
        child.stdin.write(msgB64);
        child.stdin.end();
        
    } else if (req.method === 'GET' && url.pathname === '/health') {
        res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
        res.end('OK');
    } else {
        res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
        res.end('Not Found');
    }
});

server.listen(PORT, '0.0.0.0', () => {
    console.log(`Claude Ask Server running on port ${PORT}`);
});
```

### 3.2 使用方式

```
GET /ask/claude?q=<base64编码的问题>
```

示例：
```bash
# 原始问题
curl "http://localhost:8082/ask/claude?q=$(echo '你好，请介绍一下自己' | base64)"

# 解码后实际发送的消息
你好，请介绍一下自己
```

### 3.3 响应格式

- 成功：纯文本响应（200）
- 失败：错误信息（500）

---

## 4. Docker Agent 镜像配置

所有 docker agent 镜像中已包含 Supabase agent skills 安装：

```bash
npx skills add supabase/agent-skills
```

构建完成后请执行：

```bash
docker compose up -d
```