---
name: hermit-claw
description: 创建容器化的claude agent/openclaw agent，agent对容器赋能，让容器介入智能
license: Complete terms in LICENSE.txt
---
# 首次调用本技能需要执行命令docker compose up -d --build control-18080 agent-image-claude agent-image-openclaw 

# 18080 Docker Agent 控制技能

本技能用于通过 `http://localhost:18080` 控制和调用各个 Docker agent（`claude` / `openclaw@2026.2.9`）。

## 1) 创建 agent

- 接口：`POST /api/agents`
- 请求体：

```json
{
  "type": "claude",
  "name": "writer"
}
```

- 说明：
  - `type` 仅支持：`claude`、`openclaw@2026.2.9`
  - 控制端自动分配下一个端口（从 `18081` 递增）
  - 容器命名格式：`端口号-容器名称`，例如：`18081-writer`
  - 容器端口固定映射为 `主机端口:8082`

## 2) 查询容器与卡片日志

- 接口：`GET /api/agents?tail=20`
- 返回：每个 agent 的容器名、类型、状态、端口、最近日志（用于 20 行卡片）

## 3) 给指定 agent 发送命令（核心）

- 接口：`POST /api/agents/{container_name}/command`
- 请求体：

```json
{
  "command": "ls -la /workspace"
}
```

- 返回字段：
  - `exit_code`：命令退出码
  - `output`：命令标准输出/错误输出合并文本

示例（向 `18081-writer` 发命令）：

```bash
curl -sS -X POST "http://localhost:18080/api/agents/18081-writer/command" \
  -H "Content-Type: application/json" \
  -d '{"command":"pwd && ls -la"}'
```

## 4) 查看与下载日志

- 查看：`GET /api/agents/{container_name}/logs?tail=20`
- 下载：`GET /api/agents/{container_name}/logs/download?tail=500`

## 5) 约束与约定

- 仅允许操作由控制端创建的容器（带 `hermit.managed=true` 标签）
- 日志采用 Docker `json-file` 驱动，限制为：
  - `max-size=500m`
  - `max-file=2`
