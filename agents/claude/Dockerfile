FROM node:20-bookworm-slim

RUN for i in 1 2 3 4 5; do \
        apt-get update && break || { rm -rf /var/lib/apt/lists/*; apt-get update; } \
    done \
    && apt-get install -y --no-install-recommends ca-certificates sudo git coreutils openssh-server \
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
    && ssh-keygen -A \
    && chown -R 501:20 /etc/ssh/ssh_host_*_key \
    && chmod 0600 /etc/ssh/ssh_host_*_key

ENV CLAUDE_CODE_TRUST_ALL=true
ENV CLAUDE_CODE_SKIP_ONBOARDING=true
ENV CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

USER agent
WORKDIR /home/agent
EXPOSE 8082

CMD ["/usr/sbin/sshd", "-D"]
