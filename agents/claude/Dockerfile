FROM node:20-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates sudo \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code@2.0.69

RUN useradd -m -s /bin/bash agent \
    && echo "agent ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/agent \
    && chmod 0440 /etc/sudoers.d/agent

RUN mkdir -p /home/agent/.claude \
    && printf '%s\n' '{"hasCompletedOnboarding": true, "hasTrustDialogAccepted": true, "hasCompletedProjectOnboarding": true}' > /home/agent/.claude.json \
    && chown -R agent:agent /home/agent/.claude /home/agent/.claude.json

ENV CLAUDE_CODE_TRUST_ALL=true
ENV CLAUDE_CODE_SKIP_ONBOARDING=true
ENV CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
# 我们允许使用自定义 baseUrl 并且不强制进行 OAuth 登录流程
# CLAUDE_CODE_SKIP_LOGIN 会在有些情况下导致 "Not logged in" 拦截，不再使用。依赖传入正确的 ANTHROPIC_API_KEY。

USER agent
WORKDIR /home/agent/.claude/workspace/project
EXPOSE 8082

CMD ["/bin/sh", "-lc", "mkdir -p \"$HOME/.claude\"; if [ -d /agent-config ]; then cp -R -f /agent-config/. \"$HOME/.claude/\"; fi; node -e 'const fs=require(\"fs\"); const p=process.env.HOME+\"/.claude/settings.json\"; let j={}; if(fs.existsSync(p)){ j=JSON.parse(fs.readFileSync(p,\"utf8\")); } j.trustedProjects=[\"/home/agent/.claude/workspace/project\"]; j.hasCompletedOnboarding=true; j.hasTrustDialogAccepted=true; j.hasCompletedProjectOnboarding=true; fs.writeFileSync(p, JSON.stringify(j)); fs.writeFileSync(process.env.HOME+\"/.claude.json\", JSON.stringify({hasCompletedOnboarding:true,hasTrustDialogAccepted:true,hasCompletedProjectOnboarding:true}));'; mkdir -p /home/agent/.claude/workspace/project/logs; touch /home/agent/.claude/workspace/project/logs/agent_tui.log; exec claude 2>&1 | tee -a /home/agent/.claude/workspace/project/logs/agent_tui.log"]
