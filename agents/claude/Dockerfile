FROM node:20-bookworm-slim

RUN for i in 1 2 3 4 5; do \
        apt-get update && break || { rm -rf /var/lib/apt/lists/*; apt-get update; } \
    done \
    && apt-get install -y --no-install-recommends ca-certificates sudo git coreutils openssh-server fonts-noto-cjk curl python3 python3-pip \
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
    && mkdir -p /home/agent/.claude/workspace/project/logs \
    && printf '{"hasCompletedOnboarding":true,"hasTrustDialogAccepted":true,"hasCompletedProjectOnboarding":true}' > /home/agent/.claude.json \
    && printf '#!/bin/bash\ncd /home/agent/.claude/workspace/project\nif [ -f user_start.sh ] && [ -s user_start.sh ]; then chmod +x user_start.sh; ./user_start.sh; fi\n' > /home/agent/.claude/workspace/project/start.sh \
    && chmod +x /home/agent/.claude/workspace/project/start.sh \
    && ssh-keygen -A \
    && chown -R 501:20 /home/agent/.claude /home/agent/.claude.json \
    && chown -R 501:20 /etc/ssh/ssh_host_*_key \
    && chmod 0600 /etc/ssh/ssh_host_*_key

ENV CLAUDE_CODE_TRUST_ALL=true
ENV CLAUDE_CODE_SKIP_ONBOARDING=true
ENV CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

USER agent
WORKDIR /home/agent/.claude/workspace/project
EXPOSE 8082

CMD ["/bin/sh", "-lc", "mkdir -p \"$HOME/.claude\"; mkdir -p \"$HOME/.claude/workspace/project/logs\"; if [ -d /agent-config ]; then for f in /agent-config/*; do [ \"$f\" = \"/agent-config/workspace\" ] && continue; [ -d \"$f\" ] && cp -R \"$f\" \"$HOME/.claude/\" 2>/dev/null || [ -f \"$f\" ] && cp -f \"$f\" \"$HOME/.claude/\" 2>/dev/null; done; fi; /usr/sbin/sshd; node -e 'const fs=require(\"fs\"); const p=process.env.HOME+\"/.claude/settings.json\"; let j={}; if(fs.existsSync(p)){ j=JSON.parse(fs.readFileSync(p,\"utf8\")); } j.trustedProjects=[\"/home/agent/.claude/workspace/project\"]; j.hasCompletedOnboarding=true; j.hasTrustDialogAccepted=true; j.hasCompletedProjectOnboarding=true; fs.writeFileSync(p, JSON.stringify(j)); fs.writeFileSync(process.env.HOME+\"/.claude.json\", JSON.stringify({hasCompletedOnboarding:true,hasTrustDialogAccepted:true,hasCompletedProjectOnboarding:true}));'; if [ -d \"$HOME/.claude/workspace/config-rules\" ]; then echo '[config-rules] waiting for files...'; for i in $(seq 1 30); do if [ -f \"$HOME/.claude/workspace/config-rules/run_claude.js\" ]; then cp -f \"$HOME/.claude/workspace/config-rules\"/* \"$HOME/.claude/workspace/project/\" 2>/dev/null; chmod +x \"$HOME/.claude/workspace/project/run_claude.js\" 2>/dev/null; echo '[config-rules] copied'; break; fi; echo '[config-rules] waiting... ($i/30)'; sleep 2; done; fi; if [ -f \"$HOME/.claude/workspace/project/server.js\" ]; then chmod +x \"$HOME/.claude/workspace/project/server.js\"; nohup node \"$HOME/.claude/workspace/project/server.js\" >> \"$HOME/.claude/workspace/project/logs/server.log\" 2>&1 & echo '[server] started'; fi; if [ -f \"$HOME/.claude/workspace/project/start.sh\" ] && [ -s \"$HOME/.claude/workspace/project/start.sh\" ]; then chmod +x \"$HOME/.claude/workspace/project/start.sh\"; nohup bash \"$HOME/.claude/workspace/project/start.sh\" >> \"$HOME/.claude/workspace/project/logs/start.log\" 2>&1 & fi; exec tail -f /dev/null"]
