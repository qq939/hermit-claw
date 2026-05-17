const { spawn } = require('child_process');

const child = spawn('claude', ['--dangerously-skip-permissions', '--continue', '--print'], {
    stdio: ['pipe', 'inherit', 'inherit'],
    shell: true,
    env: { ...process.env, ANTHROPIC_DISABLE_PREFLIGHT: '1', CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: '1' }
});
child.stdin.end(Buffer.from(process.env.CLAUDE_MSG, 'base64').toString('utf8'));