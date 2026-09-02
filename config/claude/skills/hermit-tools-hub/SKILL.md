# 十五、18081 Hub Tools 知识库（对接文档首页）

18081 Hub 是 Hermit 的工具知识库与对接文档中心。所有容器（工具类与普通容器端口统一，不再区分工具段）都可以选择是否注册到 Hub。注册后，该容器的调用指南（Markdown）会写入 Hub docs，并直接展示在 18081 首页上。

## 15.1 注册方式（可选）

容器启动时不再强制注册。用户可在 Control 面板的容器卡片上勾选「注册」复选框：

- 勾选注册：面板调用 `POST /api/agents/<容器名>/register`，把该容器的调用指南写入 Hub docs。
- 取消注册：面板调用 `DELETE /api/agents/<容器名>/register`，从 Hub docs 中移除。
- 同名容器重复注册会覆盖旧文档，以最新注册为准。

注册的本质：把该容器的调用指南（容器名、类型、宿主机端口、访问地址、简介、调用方式）写入 Hub 的 docs，并持久化到 config/tools_registry.json。

## 15.2 Hub 首页（对接文档）

直接访问 http://dimond.top:18081 即可查看所有已注册容器的对接文档：

- 展示每个已注册容器的 display_name / name / 宿主机端口 / 描述 / 调用指南（doc_md）。
- 暂无已注册容器时显示空提示。

## 15.3 查询接口（供 Agent 或开发者调用）

**查询全部：**

```
GET http://host.docker.internal:18081/api/tools
```

响应格式：

```json
{
  "items": [
    {
      "name": "writer",
      "port": 18200,
      "display_name": "18200-writer",
      "description": "一句话描述",
      "doc_md": "...",
      "container_name": "18200-writer",
      "agent_type": "claude"
    }
  ]
}
```

**注册单个（可选，供需要直接注册的 Agent 调用）：**

```
POST http://host.docker.internal:18081/api/tools
Content-Type: application/json
```

请求体：

```json
{
  "port": 18200,
  "name": "工具唯一名称",
  "display_name": "显示名称",
  "description": "一句话描述",
  "doc_md": "## 功能概览\n..."
}
```

**查询单个 / 删除单个：**

```
GET    http://host.docker.internal:18081/api/tools/<name>
DELETE http://host.docker.internal:18081/api/tools/<name>
```

## 15.4 注意事项

1. 注册是可选的，由用户在 Control 面板卡片上勾选决定。
2. 注册表持久化到 config/tools_registry.json（容器内挂载到 /config），重启后仍保留。
3. doc_md 应尽可能详细说明容器能力、API 端点和用法。
4. 对接文档可在 18081 Hub 首页可视化查看（http://dimond.top:18081）。
