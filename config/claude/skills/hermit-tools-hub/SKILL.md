# 十五、19081 Hub — Tools 知识库（对接文档 + 公共接口）

19081 Hub 是 Hermit 的工具知识库与对接文档中心。tools 下的每个项目（obs、email、
github 等）都可以注册到 Hub，把「自己是谁、提供哪些接口、怎么调用」展示在首页。

## 15.1 首页（工具知识库）

访问 http://dimond.top:19081：

- 底部 pills 导航：切换已注册工具。
- iframe：预览工具的 Web UI。
- Docs 查看器：查看该工具的 `doc_md` 文档。
- 首页内置两份文档：Hub 公共接口文档 + 示例工具（obs 图床）注册范本。

## 15.2 公共接口

- `GET /api/tools` — 列出所有已注册工具
- `POST /api/tools` — 注册一个工具（完整记录或简化记录）
- `GET /api/tools/{name}` — 查询单个工具详情
- `DELETE /api/tools/{name}` — 注销工具
- `GET /p/{name}/...` — 同源代理到该工具的 Web UI
- `GET /` — 首页

### 面板「注册」按钮 = 给容器下达指令（注册的正确姿势）

在 Control 面板点卡片上的「注册」，control 只会**下指令**（走容器内置接口），要求容器内的
agent 自己完成注册：

1. 读本 skill 与 `systemreadme.md` 的「核心三、注册到 Hub」；
2. 摸清本项目**真实**对外提供的接口：功能性 API（方法/路径/用途）、WebSocket、上传下载、
   静态页面等，**以及必带的 `/ask/claude`**（其他容器卡片靠它跟你对话）；
3. 生成完整记录（`doc_md` 用 Markdown：功能概览 + API 端点表 + curl 示例，地址统一
   `http://dimond.top:<你的宿主机端口>`）；
4. 自己 `POST http://host.docker.internal:19081/api/tools` 提交并确认 200。

约定：

- `name` 用容器名派生（`19083-email` → `email`），面板据此显示「已注册」；
- 再点一次「注册」= 让容器更新自己的注册信息（同名覆盖）；
- Alt+点击按钮 = 注销；
- 别把 control 当"代写方"：固定模板写出来的文档，别的卡片照着是调不通的。

### 完整记录（推荐，tools 下项目直接注册）

| 字段 | 必填 | 说明 |
|------|------|------|
| name | 是 | 工具唯一名 |
| display_name | 否 | 展示名 |
| description | 否 | 一句话描述 |
| doc_md | 否 | 完整功能接口文档（Markdown）|
| port | 否 | 宿主机端口（也可用 `host_port`）|

```json
{
  "name": "obs",
  "display_name": "OBS 图床",
  "description": "文件托管、断点续传、公告板服务",
  "port": 19082,
  "doc_md": "# OBS 图床 ..."
}
```

### 简化记录（control 面板派生）

| 字段 | 必填 | 说明 |
|------|------|------|
| container_name | 是 | 容器名，Hub 据此派生唯一 `name` |
| host_port | 否 | 宿主机端口 |
| agent_type | 否 | claude / ollama / openclaw |
| description | 否 | 一句话描述 |

```json
{
  "container_name": "19082-writer",
  "host_port": 19082,
  "agent_type": "claude",
  "description": "写作工具，提供 /ask/claude 接口"
}
```

## 15.3 调用约定

容器卡片之间的调用统一走宿主机端口：`http://dimond.top:19xxx`（xxx 为该工具分配的
宿主机端口，19081-19999 区间）。不要使用旧域名或 18xxx 端口。

## 15.4 示例工具（obs 图床）

首页内置示例工具 `obs`，作为注册范本，其 `doc_md` 覆盖完整功能接口：

- 文件上传 / 下载 / 删除，Range 分片下载
- 断点续传（`/upload/init`、`/upload/chunk/{id}/{i}`、`/upload/complete/{id}`）
- 公告板 WebSocket（`/ws`、`/notice`、`/save_notice`）

## 15.5 持久化

注册表持久化到**宿主机** `config/registry/tools_registry.json`；容器内统一看到的是
`/config/tools_registry.json`：

- control 面板容器：`./config` 挂到 `/config`，写的就是上面那个文件；
- agent 卡片：宿主机 `config/registry` 挂到卡片的 `/config`（建卡片时由 control 挂上）。

因此面板卡片上的「注册 / 已注册」与 19081 Hub 首页读的是**同一份**注册表，注册后刷新
Hub 页面即可看到。同名工具重复注册会覆盖旧记录。

> 排查提示：若 Hub 首页看不到已注册工具，先确认卡片里有 `/config/tools_registry.json`
> （`docker exec <卡片> ls -l /config`），以及 control 里 `HOST_CONFIG_ROOT` 是否指向本仓库
> 根目录下的 `config/`（compose 的 `${PWD}` 若从别的目录执行会取错路径）。
