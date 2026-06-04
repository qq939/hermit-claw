const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const TIMEOUT_MS = 3600 * 1000;
const CLAUDE_MSG = process.env.CLAUDE_MSG;
const LOG_FILE = path.join(process.env.HOME || '/home/agent', '.claude/workspace/project/logs/agent_tui.log');
const CAPTURE_STDIO = process.env.CLAUDE_CAPTURE_STDIO === '1';

if (!CLAUDE_MSG) {
    console.error('[ERROR] CLAUDE_MSG environment variable is required');
    process.exit(1);
}

const message = Buffer.from(CLAUDE_MSG, 'base64').toString('utf8');
const timestamp = new Date().toISOString().replace('T', ' ').substring(0, 19);

const logEntry = `\n[${timestamp}] $ ${message}\n`;

try {
    fs.mkdirSync(path.dirname(LOG_FILE), { recursive: true });
    fs.appendFileSync(LOG_FILE, logEntry);
} catch (e) {
    console.error('[WARN] Failed to write to log file:', e.message);
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