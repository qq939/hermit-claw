FROM debian:bookworm-slim

RUN bash -c ' \
    for attempt in 1 2 3; do \
        set +e; \
        apt-get update && apt-get install -y --no-install-recommends \
            ca-certificates sudo curl git coreutils openssh-server gnupg python3 fonts-noto-cjk \
            && break; \
        sleep 10; \
    done; \
    rm -rf /var/lib/apt/lists/*; \
    mkdir -p /var/run/sshd; \
    sed -i "s/#PermitRootLogin prohibit-password/PermitRootLogin no/" /etc/ssh/sshd_config; \
    sed -i "s/#PasswordAuthentication yes/PasswordAuthentication yes/" /etc/ssh/sshd_config; \
    sed -i "s/#PermitEmptyPasswords no/PermitEmptyPasswords no/" /etc/ssh/sshd_config \
'

RUN curl -fsSL https://ollama.com/install.sh | sh || true

RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN bash -c ' \
    for attempt in 1 2 3; do \
        set +e; \
        npm install -g @anthropic-ai/claude-code@2.0.69 && break; \
        sleep 10; \
    done \
'

COPY agents/ollama/run_claude.js /home/agent/.claude/run_claude.js

RUN bash -c ' \
    useradd -m -s /bin/bash -u 501 -g 20 agent; \
    echo "agent:agent" | chpasswd; \
    echo "agent ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/agent; \
    chmod 0440 /etc/sudoers.d/agent; \
    mkdir -p /home/agent/.claude/workspace/project/logs; \
    printf "%s" "\"{\"hasCompletedOnboarding\":true,\"hasTrustDialogAccepted\":true,\"hasCompletedProjectOnboarding\":true}\"" > /home/agent/.claude.json; \
    chmod +x /home/agent/.claude/run_claude.js; \
    printf "%s\n" "#!/bin/bash" "cd /home/agent/.claude/workspace/project" "if [ -f user_start.sh ] && [ -s user_start.sh ]; then chmod +x user_start.sh; ./user_start.sh; fi" > /home/agent/.claude/workspace/project/start.sh; \
    chmod +x /home/agent/.claude/workspace/project/start.sh; \
    ssh-keygen -A; \
    chown -R 501:20 /home/agent/.claude /home/agent/.claude.json; \
    chown -R 501:20 /etc/ssh/ssh_host_*_key; \
    chmod 0600 /etc/ssh/ssh_host_*_key \
'

ENV CLAUDE_CODE_TRUST_ALL=true
ENV CLAUDE_CODE_SKIP_ONBOARDING=true
ENV CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
ENV ANTHROPIC_BASE_URL=http://192.168.0.209:11435
ENV ANTHROPIC_AUTH_TOKEN=ollama
ENV OLLAMA_MODEL=qwen3.5

USER agent
WORKDIR /home/agent/.claude/workspace/project
EXPOSE 8082

CMD ["/bin/sh", "-lc", "mkdir -p \"$HOME/.claude\"; mkdir -p \"$HOME/.claude/workspace/project/logs\"; if [ -d /agent-config ]; then for f in /agent-config/*; do [ \"$f\" = \"/agent-config/workspace\" ] && continue; [ -d \"$f\" ] && cp -R \"$f\" \"$HOME/.claude/\" 2>/dev/null || [ -f \"$f\" ] && cp -f \"$f\" \"$HOME/.claude/\" 2>/dev/null; done; fi; /usr/sbin/sshd; if ! pgrep ollama > /dev/null 2>&1; then nohup ollama serve >> \"$HOME/.claude/workspace/project/logs/ollama.log\" 2>&1 & sleep 5; if [ -n \"$OLLAMA_MODEL\" ]; then ollama pull \"$OLLAMA_MODEL\" 2>/dev/null || true; fi; fi; node -e 'const fs=require(\"fs\"); const p=process.env.HOME+\"/.claude/settings.json\"; let j={}; if(fs.existsSync(p)){ j=JSON.parse(fs.readFileSync(p,\"utf8\")); } j.trustedProjects=[\"/home/agent/.claude/workspace/project\"]; j.hasCompletedOnboarding=true; j.hasTrustDialogAccepted=true; j.hasCompletedProjectOnboarding=true; fs.writeFileSync(p, JSON.stringify(j)); fs.writeFileSync(process.env.HOME+\"/.claude.json\", JSON.stringify({hasCompletedOnboarding:true,hasTrustDialogAccepted:true,hasCompletedProjectOnboarding:true}));'; if [ -f \"$HOME/.claude/workspace/project/start.sh\" ] && [ -s \"$HOME/.claude/workspace/project/start.sh\" ]; then chmod +x \"$HOME/.claude/workspace/project/start.sh\"; nohup bash \"$HOME/.claude/workspace/project/start.sh\" >> \"$HOME/.claude/workspace/project/logs/start.log\" 2>&1 & fi; exec tail -f /dev/null"]
