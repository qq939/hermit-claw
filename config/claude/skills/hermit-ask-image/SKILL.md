# 十、Claude Ask 图文模式接口（使用 run_claude.js）

run_claude.js 支持图文对话模式。图片通过项目根目录的 tmp.png 文件传递，
不使用 base64 内联格式。

## 10.1 工作流程

  1. 调用方将图片写入 /home/agent/.claude/workspace/project/tmp.png
  2. 调用方设置环境变量 CLAUDE_IMG=1（非空即可）
  3. run_claude.js 检测到 CLAUDE_IMG 后，在消息中追加图片引用：
     message += "\n\n![image](file:///home/agent/.claude/workspace/project/tmp.png)"
  4. Claude 读取 tmp.png 并根据消息内容进行分析

## 10.2 server.js 调用示例

```javascript
// 先将图片写入项目根目录
const imgPath = path.join(WORKSPACE_DIR, 'tmp.png');
fs.writeFileSync(imgPath, imageBuffer);

const msgB64 = Buffer.from(fullMessage).toString('base64');

const child = spawn('node', [path.join(WORKSPACE_DIR, 'run_claude.js')], {
    cwd: WORKSPACE_DIR,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: {
        ...process.env,
        ANTHROPIC_DISABLE_PREFLIGHT: '1',
        CLAUDE_CAPTURE_STDIO: '1',
        CLAUDE_MSG: msgB64,
        CLAUDE_IMG: '1'     // 触发图文模式
    }
});
```

## 10.3 注意事项

  - 图片必须保存为 /home/agent/.claude/workspace/project/tmp.png
  - CLAUDE_IMG 环境变量设为任意非空值即可触发
  - 不设置 CLAUDE_IMG 时，按纯文本模式处理（完全兼容原有逻辑）
  - 图片引用使用 file:// 绝对路径，不要用 base64 内联
  - 每次调用前会自动执行 claude --reset 清理会话缓存
  - run_claude.js 使用 --dangerously-skip-permissions --continue --print 标志运行
