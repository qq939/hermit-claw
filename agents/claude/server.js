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