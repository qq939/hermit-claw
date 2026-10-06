#!/bin/sh
# Hermit agent 容器看门狗：8082 上的 web app 不响应就重跑 start.sh。
#
# 背景（实测踩到）：容器启动时 CMD 只拉一次 start.sh，偶发失败就再没有第二次机会
# ——18081-hub 卡片重启后 web 没起来，它的 logs/start.log 里一条记录都没有。
# 这里每 30 秒探测一次 8082：连不上就重跑 start.sh（幂等：start.sh → user_start.sh
# 会先清理旧进程再拉起）。
#
# 细节：
#   - 仅当 user_start.sh 存在时才管（有些卡片本来就没有 web app）；
#   - 用 node 探测而不是 curl：agent 镜像里一定有 node，且 curl 在探测失败时
#     会输出 000（配合 `|| echo 000` 会拼成 000000，容易踩坑）；
#   - 任何 HTTP 响应（哪怕 404）都算活着，只有"完全连不上"才重启。

while true; do
    sleep 30
    [ -s "$HOME/.claude/workspace/project/user_start.sh" ] || continue
    if ! node -e '
        const http = require("http");
        const req = http.get({ host: "127.0.0.1", port: 8082, path: "/", timeout: 3000 }, () => process.exit(0));
        req.on("error", () => process.exit(1));
        req.on("timeout", () => { req.destroy(); process.exit(1); });
    ' >/dev/null 2>&1; then
        echo "[watchdog] 8082 no response; re-running start.sh"
        bash "$HOME/.claude/workspace/project/start.sh" >> "$HOME/.claude/workspace/project/logs/start.log" 2>&1
    fi
done
