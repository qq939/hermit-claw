# 十四、Claude Ask Server 服务

每个 claude agent 卡片都要有一个初始的 server.js 服务，端口 8082，路径 `/ask/claude`，GET 访问，参数 `q="你要问的问题"`。支持 base64 编码，返回纯文本。底层必须调用 `run_claude.js`。

## server.js 实现

```javascript
const http = require('http');
const path = require('path');
const { spawn } = require('child_process');

const PORT = 8082;
const WORKSPACE_DIR = '/home/agent/.claude/workspace/project';
const TIMEOUT_MS = 3600 * 1000;

// 完整实现见 /home/agent/.claude/workspace/project/server.js
// GET /ask/claude?q=<query> 调用 run_claude.js
// GET /health 健康检查
```

## 使用方式

```
GET /ask/claude?q=<普通字符串或base64编码>
```

示例：
```bash
# 普通字符串（自动识别）
curl "http://localhost:8082/ask/claude?q=你好，请介绍一下自己"

# base64 编码（用于复杂内容）
curl "http://localhost:8082/ask/claude?q=$(echo '你好，请介绍一下自己' | base64)"
```

智能识别规则：
- 参数包含空格或长度 < 50：当作普通字符串，`decodeURIComponent(q)`
- 其他情况：当作 base64 编码

## 响应格式

- 成功：纯文本响应（200）
- 失败：错误信息（500）
