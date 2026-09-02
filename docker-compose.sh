#!/usr/bin/env bash
# docker-compose.sh
# Hermit 部署脚本（适配 Linux / macOS）：
#   1) 从 config/hermit_settings.json 读取起始端口 start_port
#   2) 恢复 docker-compose.yml 为默认占位状态（18080）
#   3) 将 docker-compose.yml 中的 18080 动态替换为 start_port
#   4) 执行 docker compose 部署 control 服务
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

# 2. 恢复 docker-compose.yml 为默认占位（18080），保证脚本可重复执行
if ! git -C "$SCRIPT_DIR" checkout -- docker-compose.yml 2>/dev/null; then
    echo "警告: git checkout 恢复 docker-compose.yml 失败，使用当前文件继续"
fi

# 3. 将 18080 动态替换为目标端口（service 名 / container_name / ports 映射）
#    sed -i.bak 写法在 Linux 和 macOS 上均可用，替换完成后删除备份文件
sed -i.bak "s/18080/$PORT/g" "$COMPOSE_PATH"
rm -f "$COMPOSE_PATH.bak"
echo "已将 docker-compose.yml 中的 18080 替换为 $PORT"

# 4. 部署 control 服务
echo "开始部署 control-$PORT 服务..."
docker compose up -d --build "control-$PORT"

echo "部署完成，控制面板访问地址: http://localhost:$PORT"
