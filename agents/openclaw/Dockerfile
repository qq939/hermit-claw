FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates sudo curl git \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g openclaw@2026.2.9

RUN useradd -m -s /bin/bash agent \
    && echo "agent ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/agent \
    && chmod 0440 /etc/sudoers.d/agent

USER agent
WORKDIR /home/agent/.openclaw/workspace/project
EXPOSE 8082

CMD ["/bin/sh", "-lc", "mkdir -p \"$HOME/.openclaw\"; if [ -d /agent-config ]; then cp -R -f /agent-config/. \"$HOME/.openclaw/\"; fi; node -e 'const fs=require(\"fs\"); const p=process.env.HOME+\"/.openclaw/openclaw.json\"; if(fs.existsSync(p)){ const j=JSON.parse(fs.readFileSync(p,\"utf8\")); if(j.agents && j.agents.defaults){ j.agents.defaults.workspace=\"/home/agent/.openclaw/workspace/project\"; } j.gateway = j.gateway || {}; j.gateway.auth = j.gateway.auth || {}; j.gateway.remote = j.gateway.remote || {}; j.gateway.url = \"ws://127.0.0.1:18790\"; if(j.gateway.auth.token){ j.gateway.remote.token = j.gateway.auth.token; } fs.writeFileSync(p, JSON.stringify(j, null, 2)); }'; mkdir -p /home/agent/.openclaw/workspace/project/logs; OPENCLAW_GATEWAY_TOKEN=\"$(node -e 'const fs=require(\"fs\"); const p=process.env.HOME+\"/.openclaw/openclaw.json\"; const j=JSON.parse(fs.readFileSync(p,\"utf8\")); process.stdout.write((j.gateway&&j.gateway.auth&&j.gateway.auth.token)||\"\");')\"; export OPENCLAW_GATEWAY_TOKEN; nohup openclaw gateway run --force --token \"$OPENCLAW_GATEWAY_TOKEN\" --port 18790 --ws-log compact --verbose >/home/agent/.openclaw/workspace/project/logs/gateway.log 2>&1 & sleep 3; nohup openclaw tui >/home/agent/.openclaw/workspace/project/logs/agent_tui.log 2>&1 & exec tail -F /home/agent/.openclaw/workspace/project/logs/agent_tui.log /home/agent/.openclaw/workspace/project/logs/gateway.log"]
