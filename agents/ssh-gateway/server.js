const { WebSocketServer } = require('ws');
const { spawn, readFileSync, readdirSync, statSync } = require('fs');
const { join, basename } = require('path');
const http = require('http');

const PORT = process.env.PORT || 8080;
const DOCKER_HOST = process.env.DOCKER_HOST || 'host.docker.internal';
const SSH_USER = process.env.SSH_USER || 'agent';
const SSH_PASS = process.env.SSH_PASS || 'agent';
const RULES_DIR = process.env.RULES_DIR || '/rules';

const server = http.createServer((req, res) => {
    if (req.url === '/health') {
        res.writeHead(200);
        res.end('OK');
        return;
    }
    if (req.url.startsWith('/rules/') || req.url === '/rules') {
        const urlPath = req.url === '/rules' ? '/' : req.url.slice('/rules/'.length);
        if (req.url === '/rules' || req.url === '/rules/') {
            try {
                const files = readdirSync(RULES_DIR).filter(f => statSync(join(RULES_DIR, f)).isFile());
                res.writeHead(200, {'Content-Type': 'application/json'});
                res.end(JSON.stringify({ files }));
                return;
            } catch (e) {
                res.writeHead(500);
                res.end('Rules dir error');
                return;
            }
        }
        const filename = basename(urlPath);
        const filepath = join(RULES_DIR, filename);
        try {
            const content = readFileSync(filepath);
            res.writeHead(200, {'Content-Type': 'application/octet-stream', 'Content-Disposition': `attachment; filename="${filename}"`});
            res.end(content);
        } catch (e) {
            res.writeHead(404);
            res.end('File not found');
        }
        return;
    }
    res.writeHead(404);
    res.end('Not found');
});

const wss = new WebSocketServer({ server });

wss.on('connection', (ws, req) => {
    const url = new URL(req.url, `http://localhost`);
    const targetPort = url.searchParams.get('port');

    if (!targetPort) {
        ws.close(4000, 'Missing port parameter');
        return;
    }

    const sshPort = parseInt(targetPort);
    console.log(`SSH connection requested for port ${sshPort}`);

    const proc = spawn('sshpass', [
        '-p', SSH_PASS,
        'ssh', '-o', 'StrictHostKeyChecking=no',
        '-o', 'UserKnownHostsFile=/dev/null',
        '-tt',
        '-p', String(sshPort),
        `${SSH_USER}@${DOCKER_HOST}`
    ], {
        stdio: ['pipe', 'pipe', 'pipe']
    });

    proc.on('error', (err) => {
        console.error('SSH process error:', err.message);
        ws.close(4001, err.message);
    });

    proc.stdout.on('data', (data) => {
        if (ws.readyState === ws.OPEN) {
            ws.send(data.toString());
        }
    });

    proc.stderr.on('data', (data) => {
        if (ws.readyState === ws.OPEN) {
            ws.send(data.toString());
        }
    });

    proc.on('close', (code) => {
        console.log(`SSH process closed with code ${code}`);
        if (ws.readyState === ws.OPEN) {
            ws.close(1000, `Process exited with code ${code}`);
        }
    });

    ws.on('message', (msg) => {
        proc.stdin.write(msg.toString());
    });

    ws.on('close', () => {
        proc.kill();
    });

    ws.on('error', () => {
        proc.kill();
    });
});

server.listen(PORT, '0.0.0.0', () => {
    console.log(`SSH Gateway running on port ${PORT}`);
});
