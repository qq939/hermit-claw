FROM node:20-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates sudo coreutils openssh-server \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir /var/run/sshd \
    && sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin no/' /etc/ssh/sshd_config \
    && sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config \
    && sed -i 's/#PermitEmptyPasswords no/PermitEmptyPasswords no/' /etc/ssh/sshd_config

RUN npm install -g @anthropic-ai/claude-code@2.0.69

RUN useradd -m -s /bin/bash -u 501 -g 20 agent \
    && echo "agent:agent" | chpasswd \
    && echo "agent ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/agent \
    && chmod 0440 /etc/sudoers.d/agent \
    && mkdir -p /home/agent/.claude \
    && printf '%s\n' '{"hasCompletedOnboarding": true, "hasTrustDialogAccepted": true, "hasCompletedProjectOnboarding": true}' > /home/agent/.claude.json \
    && chown -R 501:20 /home/agent/.claude /home/agent/.claude.json \
    && mkdir -p /home/agent/.claude/workspace/project/logs \
    && printf 'const { spawn } = require("child_process"); const child = spawn("claude", ["--dangerously-skip-permissions", "--continue", "--print"], { stdio: ["pipe", "inherit", "inherit"], shell: true, env: { ...process.env, ANTHROPIC_DISABLE_PREFLIGHT: "1" } }); child.stdin.end(Buffer.from(process.env.CLAUDE_MSG, "base64").toString("utf8"));\n' > /home/agent/.claude/run_claude.js \
    && chmod +x /home/agent/.claude/run_claude.js \
    && printf '#!/bin/bash\ncd /home/agent/.claude/workspace/project\nif [ -f user_start.sh ] && [ -s user_start.sh ]; then chmod +x user_start.sh; ./user_start.sh; fi\n' > /home/agent/.claude/workspace/project/start.sh \
    && chmod +x /home/agent/.claude/workspace/project/start.sh \
    && ssh-keygen -A \
    && chown -R 501:20 /etc/ssh/ssh_host_*_key \
    && chmod 0600 /etc/ssh/ssh_host_*_key

ENV CLAUDE_CODE_TRUST_ALL=true
ENV CLAUDE_CODE_SKIP_ONBOARDING=true
ENV CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

USER agent
WORKDIR /home/agent/.claude/workspace/project
EXPOSE 8082

CMD ["/bin/sh", "-lc", " \
    mkdir -p \"$HOME/.claude\"; \
    if [ -d /agent-config ]; then cp -R -f /agent-config/. \"$HOME/.claude/\"; fi; \
    mkdir -p /home/agent/.claude/workspace/project/logs; \
    /usr/sbin/sshd; \
    node -e 'const fs=require(\"fs\"); const p=process.env.HOME+\"/.claude/settings.json\"; let j={}; if(fs.existsSync(p)){ j=JSON.parse(fs.readFileSync(p,\"utf8\")); } j.trustedProjects=[\"/home/agent/.claude/workspace/project\"]; j.hasCompletedOnboarding=true; j.hasTrustDialogAccepted=true; j.hasCompletedProjectOnboarding=true; fs.writeFileSync(p, JSON.stringify(j)); fs.writeFileSync(process.env.HOME+\"/.claude.json\", JSON.stringify({hasCompletedOnboarding:true,hasTrustDialogAccepted:true,hasCompletedProjectOnboarding:true}));'; \
    if [ -f /home/agent/.claude/workspace/project/start.sh ] && [ -s /home/agent/.claude/workspace/project/start.sh ]; then \
        chmod +x /home/agent/.claude/workspace/project/start.sh; \
        nohup bash /home/agent/.claude/workspace/project/start.sh >> /home/agent/.claude/workspace/project/logs/start.log 2>&1 & \
    fi; \
    exec tail -f /dev/null"]
