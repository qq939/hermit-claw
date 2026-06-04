FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gnupg ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code@2.0.69

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app.py /app/app.py

RUN ln -s /config /app/config

EXPOSE 8080

CMD ["sh", "-lc", "mkdir -p /root/.claude; if [ -f /config/claude/config.json ]; then cp /config/claude/config.json /root/.claude/config.json; fi; if [ -f /config/claude/settings.json ]; then cp /config/claude/settings.json /root/.claude/settings.json; fi; echo '{\"hasCompletedOnboarding\":true,\"hasTrustDialogAccepted\":true,\"hasCompletedProjectOnboarding\":true}' > /root/.claude.json; python app.py"]