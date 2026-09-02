# 十五、19081 Hub Tools 知识库（对接文档首页）

19081 Hub 是 Hermit 的工具知识库与对接文档中心。所有容器（工具类与普通容器端口统一，不再区分工具段）都可以选择是否注册到 Hub。注册后，该容器的调用指南（Markdown）会写入 Hub docs，并直接展示在 19081 首页上。

## 15.1 注册方式（可选）

容器启动时不再强制注册。用户可在 Control 面板的容器卡片上勾选「注册」复选框：

- 勾选注册：面板调用 `POST /api/agents/<容器名>/register`，把该容器的调用指南写入 Hub docs。
- 取消注册：面板调用 `DELETE /api/agents/<容器名>/register`，从 Hub docs 中移除。
- 同名容器重复注册会覆盖旧文档，以最新注册为准。

注册的本质：把该容器的调用指南（容器名、类型、宿主机端口、访问地址、简介、调用方式）写入 Hub 的 docs，并持久化到 config/tools_registry.json。

## 15.2 Hub 首页（对接文档）

直接访问 http://dimond.top:19081 即可查看所有已注册容器的对接文档：

- 展示每个已注册容器的 display_name / name / 宿主机端口 / 描述 / 调用指南（doc_md）。
- 暂无已注册容器时显示空提示。

## 15.3 查询接口（供 Agent 或开发者调用）

**查询全部：**

```
GET http://host.docker.internal:19081/api/tools
```

响应格式：

```json
{
  "items": [
    {
      "name": "writer",
      "port": 19200,
      "display_name": "19200-writer",
      "description": "一句话描述",
      "doc_md": "...",
      "container_name": "19200-writer",
      "agent_type": "claude"
    }
  ]
}
```

**注册单个（公共接口规范，供需要直接注册的 Agent 调用）：**

```
POST http://host.docker.internal:19081/api/tools
Content-Type: application/json
```

请求体使用公共字段（`container_name` 必填，其余可选）：

| 字段 | 必填 | 说明 |
|------|------|------|
| container_name | 是 | 容器名，Hub 据此派生唯一 `name` |
| host_port | 否 | 宿主机访问端口 |
| agent_type | 否 | 容器类型：claude / ollama / openclaw |
| description | 否 | 一句话描述，写入 doc_md |

```json
{
  "container_name": "19082-writer",
  "host_port": 19082,
  "agent_type": "claude",
  "description": "写作工具，提供 /ask/claude 接口"
}
```

Hub 内部会把上述公共字段归一化为完整记录（`name` 由 container_name 派生，
`port` 取自 host_port，`doc_md` 自动生成）。也可直接传完整记录（`name`/`port`/
`display_name`/`description`/`doc_md`），Hub 原样接收。

**查询单个 / 删除单个：**

```
GET    http://host.docker.internal:19081/api/tools/<name>
DELETE http://host.docker.internal:19081/api/tools/<name>
```

## 15.4 注意事项

1. 注册是可选的，由用户在 Control 面板卡片上勾选决定。
2. 注册表持久化到 config/tools_registry.json（容器内挂载到 /config），重启后仍保留。
3. doc_md 应尽可能详细说明容器能力、API 端点和用法。
4. 对接文档可在 19081 Hub 首页可视化查看（http://dimond.top:19081）。
