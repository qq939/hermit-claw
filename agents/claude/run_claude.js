const { spawn } = require('child_process');

const msg = Buffer.from(process.env.CLAUDE_MSG, 'base64').toString('utf8');
const env = { ...process.env, ANTHROPIC_DISABLE_PREFLIGHT: '1' };

spawn('claude', ['--dangerously-skip-permissions', '--continue', '--print', msg], {
    stdio: 'inherit',
    shell: true,
    env
});
