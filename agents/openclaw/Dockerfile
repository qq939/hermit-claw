FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates sudo curl git coreutils \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g openclaw@2026.2.9

RUN useradd -m -s /bin/bash agent \
    && echo "agent ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/agent \
    && chmod 0440 /etc/sudoers.d/agent

USER agent
WORKDIR /home/agent/.openclaw/workspace/project
EXPOSE 8082

CMD ["/bin/sh", "-lc", "mkdir -p \"$HOME/.openclaw\"; if [ -d /agent-config ]; then cp -R -f /agent-config/. \"$HOME/.openclaw/\"; fi; mkdir -p /home/agent/.openclaw/workspace/project/logs; export GATEWAY_HOST=\"${OPENCLAW_GATEWAY_HOST:-172.30.0.10}\"; export GATEWAY_PORT=\"${OPENCLAW_GATEWAY_PORT:-18790}\"; export GATEWAY_TOKEN=\"${OPENCLAW_GATEWAY_TOKEN:-}\"; node -e 'const fs=require(\"fs\"); const p=process.env.HOME+\"/.openclaw/openclaw.json\"; if(fs.existsSync(p)){ const j=JSON.parse(fs.readFileSync(p,\"utf8\")); if(j.agents && j.agents.defaults){ j.agents.defaults.workspace=\"/home/agent/.openclaw/workspace/project\"; } j.gateway = j.gateway || {}; j.gateway.port = 18790; j.gateway.auth = j.gateway.auth || {}; j.gateway.remote = j.gateway.remote || {}; j.gateway.remote.url = \"ws://\" + process.env.GATEWAY_HOST + \":\" + process.env.GATEWAY_PORT; if(j.gateway.auth.token){ j.gateway.remote.token = j.gateway.auth.token; } fs.writeFileSync(p, JSON.stringify(j, null, 2)); }'; exec openclaw tui --url \"ws://$GATEWAY_HOST:$GATEWAY_PORT\" --token \"$GATEWAY_TOKEN\""]
