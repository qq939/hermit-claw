#!/usr/bin/env bash
# docker-compose.sh
# Hermit 部署脚本（适配 Linux / macOS）：
#   1) 从 config/hermit_settings.json 读取起始端口 start_port
#   2) 恢复 docker-compose.yml 为默认占位状态（基准 18080）
#   3) 按 PORT_OFFSET = start_port - 18080 重写所有 18xxx 宿主机端口。
#      容器内部端口（8080 / 8088 / 5030 / 18790 / 22）保持不变。
#   4) 构建 agent 模板镜像（带 profiles: ["templates"]，默认 up 不构建，需显式构建）
#   5) 执行 docker compose 部署 control 服务
# 说明：端口来自配置文件，不硬编码，修改 hermit_settings.json 后重新运行即可生效。

set -euo pipefail

# 脚本所在目录（保证从任意目录运行都能正确定位文件）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS_PATH="$SCRIPT_DIR/config/hermit_settings.json"
COMPOSE_PATH="$SCRIPT_DIR/docker-compose.yml"

# 1. 读取配置端口
if [ ! -f "$SETTINGS_PATH" ]; then
    echo "错误: 配置文件不存在: $SETTINGS_PATH" >&2
    exit 1
fi

PORT=$(grep -Eo '"start_port"[[:space:]]*:[[:space:]]*[0-9]+' "$SETTINGS_PATH" | grep -Eo '[0-9]+' | head -n1 || true)
if [ -z "$PORT" ]; then
    echo "错误: hermit_settings.json 中缺少 start_port 字段" >&2
    exit 1
fi
echo "目标起始端口: $PORT"

# 2. 恢复 docker-compose.yml 为默认占位（基准 18080），保证脚本可重复执行
if ! git -C "$SCRIPT_DIR" checkout -- docker-compose.yml 2>/dev/null; then
    echo "警告: git checkout 恢复 docker-compose.yml 失败，使用当前文件继续"
fi

# 3. 按偏移量重写所有宿主机 18xxx 端口
BASE=18080
OFFSET=$((PORT - BASE))
CONTROL=$((18080 + OFFSET))     # 控制面：service 名 / container 名 / 宿主端口
OBS=$((18000 + OFFSET))         # obs 工具：service 名 / container 名 / 宿主端口 / HOST_PORT
EMAIL=$((18001 + OFFSET))       # email 工具：service 名 / container 名 / 宿主端口 / HOST_PORT
HUB=$((18081 + OFFSET))         # 工具 Hub：TOOLS_HUB_URL
SSH=$((18800 + OFFSET))         # ssh 网关宿主端口
GATEWAY_HOST=$((18790 + OFFSET)) # openclaw 网关：只改宿主侧，容器侧 18790 保持不变

# sed -i.bak 在 Linux 与 macOS 上均可用，替换完成后删除备份文件。
# 第一条只改 openclaw-gateway 的宿主侧，避免误改 OPENCLAW_GATEWAY_PORT=18790（容器内部端口）。
sed -i.bak \
    -e "s/\"18790:18790\"/\"$GATEWAY_HOST:18790\"/g" \
    -e "s/18080/$CONTROL/g" \
    -e "s/18000/$OBS/g" \
    -e "s/18001/$EMAIL/g" \
    -e "s/18081/$HUB/g" \
    -e "s/18800/$SSH/g" \
    "$COMPOSE_PATH"
rm -f "$COMPOSE_PATH.bak"
echo "已重写 docker-compose.yml 宿主机端口 (offset=$OFFSET)"

# 4. 构建 agent 模板镜像（带 profiles: ["templates"]，默认 up 不构建，需显式构建）
echo "构建 agent 模板镜像..."
docker compose build agent-image-claude agent-image-openclaw agent-image-ollama

# 5. 部署 control 服务
echo "开始部署 control-$PORT 服务..."
docker compose up -d --build "control-$PORT"

echo "部署完成，控制面板访问地址: http://localhost:$PORT"
