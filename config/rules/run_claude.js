const { spawn } = require('child_process');

const TIMEOUT_MS = 3600 * 1000;

const child = spawn('claude', ['--dangerously-skip-permissions', '--continue', '--print'], {
    stdio: ['pipe', 'inherit', 'inherit'],
    shell: true,
    env: { ...process.env, ANTHROPIC_DISABLE_PREFLIGHT: '1' }
});

const timeout = setTimeout(() => {
    console.error('[TIMEOUT] Claude process killed after 60 minutes');
    child.kill('SIGTERM');
    setTimeout(() => child.kill('SIGKILL'), 5000);
}, TIMEOUT_MS);

child.on('close', () => clearTimeout(timeout));
child.on('error', () => clearTimeout(timeout));

child.stdin.end(Buffer.from(process.env.CLAUDE_MSG, 'base64').toString('utf8'));