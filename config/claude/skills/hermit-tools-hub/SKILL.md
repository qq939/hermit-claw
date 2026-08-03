# 十五、18081 Hub Tools 知识库接口（工具注册与文档查询）

18081 Hub 是 Hermit 工具知识库，所有工具类（端口 18000-18079）的功能文档都需要向 Hub 注册。Agent 可以通过以下接口注册和查询工具文档。

## 15.1 注册工具文档（Agent 必须执行）

每个工具容器启动后，应将自身的功能文档（Markdown 格式）注册到 18081 Hub，
以便其他 Agent 和开发者查询工具功能。

**注册接口：**
```
POST http://host.docker.internal:18081/api/tools
Content-Type: application/json
```

**请求体（JSON）：**
```json
{
  "port": 18000,
  "name": "工具名称（唯一标识）",
  "display_name": "工具显示名称",
  "description": "一句话简要描述",
  "doc_md": "## 功能概览\n\n| 功能 | 说明 |\n|------|------|\n..."
}
```

**字段说明：**
- `port`（必填）：工具的宿主机端口（18000-18079）
- `name`（必填）：工具唯一名称，用于后续查询（如 "obs", "email"）
- `display_name`：友好的显示名称
- `description`：一句话简要描述工具功能
- `doc_md`：完整的工具文档，Markdown 格式。建议包含：
  - 功能概览（表格）
  - 所有 API 端点及说明（方法、路径、功能）
  - 请求/响应格式示例
  - curl 使用示例

**完整示例（bash）：**
```bash
curl -X POST http://host.docker.internal:18081/api/tools \
  -H "Content-Type: application/json" \
  -d '{
    "port": 18000,
    "name": "my-tool",
    "display_name": "我的工具",
    "description": "这是我的 MCP 工具服务的简要描述",
    "doc_md": "## 功能概览\n\n| 功能 | 说明 |\n|------|------|\n| 功能1 | 描述1 |\n| 功能2 | 描述2 |\n\n## API 端点\n\n| 方法 | 路径 | 说明 |\n|------|------|------|\n| GET | `/` | Web UI |\n| POST | `/api/v1/do` | 执行操作 |\n\n## 使用示例\n\n```bash\ncurl http://dimond.top:18000/api/v1/do\n```"
  }'
```

注意：同名工具重复注册会覆盖旧文档，以最新注册为准。

## 15.2 查询已注册的工具文档

Agent 可以查询所有已注册工具的文档信息。

**查询接口：**
```
GET http://host.docker.internal:18081/api/tools
```

**响应格式：**
```json
{
  "items": [
    {
      "name": "obs",
      "port": 18000,
      "display_name": "OBS 图床",
      "description": "文件托管、存储桶服务",
      "doc_md": "...",
      "registered_at": "2026-08-03T14:30:00Z"
    }
  ]
}
```

## 15.3 注意事项

1. 工具容器启动后应立即注册文档（放在启动脚本末执行或首次完成开发后执行）
2. 每次重启容器后重新注册（Hub 仅在内存中存储，重启后清空）
3. `doc_md` 应尽可能详细说明工具的所有能力、API 端点和用法
4. 工具文档可在 18081-Hub Web UI 中可视化查看（http://dimond.top:18081）
