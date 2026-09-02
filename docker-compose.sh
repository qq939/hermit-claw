#!/usr/bin/env bash
# docker-compose.sh
# Hermit 部署脚本（适配 Linux / macOS）：端口已固定为 19xxx（19080 控制面板 / 19081 工具 Hub）。
# 脚本不再做任何字符串替换或端口偏移，直接部署 docker-compose.yml 中已写好的 control-19080 服务。

set -euo pipefail

# 脚本所在目录（保证从任意目录运行都能正确定位文件）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 构建 agent 模板镜像（带 profiles: ["templates"]，默认 compose up 不会构建，需显式构建）
docker compose build agent-image-claude agent-image-openclaw agent-image-ollama

# 部署 control 服务（docker-compose.yml 已固定 control-19080: 19080/19081 端口映射）
docker compose up -d --build control-19080

echo "部署完成，控制面板访问地址: http://localhost:19080"
echo "工具 Hub 对接文档: http://localhost:19081"
