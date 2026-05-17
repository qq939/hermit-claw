const { spawn } = require('child_process');

const msgBase64 = process.env.CLAUDE_MSG;
const decoded = Buffer.from(msgBase64, 'base64').toString('utf8');

const child = spawn('claude', [
    '--dangerously-skip-permissions',
    '--resume',
    '-p', '/dev/stdin',
    '--print'
], {
    stdio: ['pipe', 'inherit', 'inherit'],
    shell: true,
    env: { 
        ...process.env, 
        ANTHROPIC_DISABLE_PREFLIGHT: '1',
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: '1'
    }
});
child.stdin.end(decoded);