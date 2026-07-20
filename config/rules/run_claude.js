const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const TIMEOUT_MS = 3600 * 1000;
const CLAUDE_MSG = process.env.CLAUDE_MSG;
const CLAUDE_IMG = process.env.CLAUDE_IMG;  // 可选，图片base64编码
const LOG_FILE = path.join(process.env.HOME || '/home/agent', '.claude/workspace/project/logs/agent_tui.log');
const CAPTURE_STDIO = process.env.CLAUDE_CAPTURE_STDIO === '1';
const WORKSPACE_DIR = path.join(process.env.HOME || '/home/agent', '.claude/workspace/project');

if (!CLAUDE_MSG) {
    console.error('[ERROR] CLAUDE_MSG environment variable is required');
    process.exit(1);
}

let message = Buffer.from(CLAUDE_MSG, 'base64').toString('utf8');
const timestamp = new Date().toISOString().replace('T', ' ').substring(0, 19);

const logEntry = `\n[${timestamp}] $ ${message}\n`;

try {
    fs.mkdirSync(path.dirname(LOG_FILE), { recursive: true });
    fs.appendFileSync(LOG_FILE, logEntry);
} catch (e) {
    console.error('[WARN] Failed to write to log file:', e.message);
}

// 处理图片（可选）
if (CLAUDE_IMG) {
    const imgPath = path.join(WORKSPACE_DIR, 'tmp.png');
    try {
        // 确保是有效的 base64 数据
        let imgData = CLAUDE_IMG;
        if (imgData.includes(',')) {
            imgData = imgData.split(',')[1];
        }
        const buffer = Buffer.from(imgData, 'base64');
        fs.writeFileSync(imgPath, buffer);
        console.error(`[IMG] Image saved to: ${imgPath}`);
        // 使用 Claude Code 能识别的图片引用格式
        message += `\n\n![image](file://${imgPath})`;
    } catch (e) {
        console.error('[WARN] Failed to save image:', e.message);
    }
}

const child = spawn('claude', ['--dangerously-skip-permissions', '--continue', '--print', '-'], {
    stdio: ['pipe', 'pipe', 'pipe'],
    shell: true,
    env: { ...process.env, ANTHROPIC_DISABLE_PREFLIGHT: '1' }
});

const timeout = setTimeout(() => {
    console.error('[TIMEOUT] Claude process killed after 60 minutes');
    child.kill('SIGTERM');
    setTimeout(() => child.kill('SIGKILL'), 5000);
}, TIMEOUT_MS);

if (child.stdout) {
    child.stdout.on('data', (data) => {
        const text = data.toString();
        try { fs.appendFileSync(LOG_FILE, text); } catch (e) {}
        if (CAPTURE_STDIO) process.stdout.write(text);
    });
}

if (child.stderr) {
    child.stderr.on('data', (data) => {
        const text = data.toString();
        try { fs.appendFileSync(LOG_FILE, text); } catch (e) {}
        if (CAPTURE_STDIO) process.stderr.write(text);
    });
}

child.on('close', (code) => {
    clearTimeout(timeout);
    process.exit(code);
});

child.on('error', (err) => {
    clearTimeout(timeout);
    console.error('[ERROR]', err.message);
    process.exit(1);
});

child.stdin.write(message);
child.stdin.end();