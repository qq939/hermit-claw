FROM node:22-bookworm-slim

RUN bash -c ' \
    for attempt in 1 2 3; do \
        set +e; \
        apt-get update && apt-get install -y --no-install-recommends ca-certificates sudo curl git coreutils openssh-server && break; \
        sleep 10; \
    done; \
    rm -rf /var/lib/apt/lists/*; \
    mkdir -p /var/run/sshd; \
    sed -i "s/#PermitRootLogin prohibit-password/PermitRootLogin no/" /etc/ssh/sshd_config; \
    sed -i "s/#PasswordAuthentication yes/PasswordAuthentication yes/" /etc/ssh/sshd_config; \
    sed -i "s/#PermitEmptyPasswords no/PermitEmptyPasswords no/" /etc/ssh/sshd_config; \
    useradd -m -s /bin/bash -u 501 -g 20 agent; \
    echo "agent:agent" | chpasswd; \
    echo "agent ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/agent; \
    chmod 0440 /etc/sudoers.d/agent; \
    mkdir -p /home/agent/.openclaw/workspace/project/logs; \
    printf "#!/bin/bash\ncd /home/agent/.openclaw/workspace/project\nif [ -f user_start.sh ] && [ -s user_start.sh ]; then chmod +x user_start.sh; ./user_start.sh; fi\n" > /home/agent/.openclaw/workspace/project/start.sh; \
    chmod +x /home/agent/.openclaw/workspace/project/start.sh; \
    ssh-keygen -A; \
    chown -R 501:20 /etc/ssh/ssh_host_*_key; \
    chmod 0600 /etc/ssh/ssh_host_*_key \
'

RUN bash -c ' \
    for attempt in 1 2 3; do \
        set +e; \
        npm install -g openclaw@2026.2.9 && break; \
        sleep 15; \
    done \
'

USER agent
WORKDIR /home/agent/.openclaw/workspace/project
EXPOSE 8082

CMD ["/bin/sh", "-lc", " \
    mkdir -p \"$HOME/.openclaw\"; \
    if [ -d /agent-config ]; then cp -R -f /agent-config/. \"$HOME/.openclaw/\"; fi; \
    mkdir -p /home/agent/.openclaw/workspace/project/logs; \
    /usr/sbin/sshd; \
    node -e ' \
        const fs=require(\"fs\"); \
        const gh=process.env.OPENCLAW_GATEWAY_HOST||\"172.30.0.10\"; \
        const gp=process.env.OPENCLAW_GATEWAY_PORT||\"18790\"; \
        const p=process.env.HOME+\"/.openclaw/openclaw.json\"; \
        if(fs.existsSync(p)){ \
            const j=JSON.parse(fs.readFileSync(p,\"utf8\")); \
            if(j.agents && j.agents.defaults){ \
                j.agents.defaults.workspace=\"/home/agent/.openclaw/workspace/project\"; \
            } \
            j.gateway = j.gateway || {}; \
            j.gateway.port = 18790; \
            j.gateway.auth = j.gateway.auth || {}; \
            j.gateway.remote = j.gateway.remote || {}; \
            j.gateway.remote.url = \"ws://\" + gh + \":\" + gp; \
            if(j.gateway.auth.token){ \
                j.gateway.remote.token = j.gateway.auth.token; \
            } \
            delete j.gateway.bind; \
            delete j.gateway.mode; \
            fs.writeFileSync(p, JSON.stringify(j, null, 2)); \
        } \
    '; \
    if [ -f /home/agent/.openclaw/workspace/project/start.sh ] && [ -s /home/agent/.openclaw/workspace/project/start.sh ]; then \
        chmod +x /home/agent/.openclaw/workspace/project/start.sh; \
        nohup bash /home/agent/.openclaw/workspace/project/start.sh >> /home/agent/.openclaw/workspace/project/logs/start.log 2>&1 & \
    fi; \
    exec openclaw tui --url \"ws://$OPENCLAW_GATEWAY_HOST:$OPENCLAW_GATEWAY_PORT\" --token \"$OPENCLAW_GATEWAY_TOKEN\""]
