FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates sudo openssh-client sshpass python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY package.json .
RUN npm install

COPY server.js .

EXPOSE 8080

CMD ["node", "server.js"]
