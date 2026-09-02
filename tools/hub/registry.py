# -*- coding: utf-8 -*-
"""Hermit Tools Hub 注册表（纯标准库，无 flask/docker 依赖，便于单测）。

职责：
  - 维护已注册工具的持久化注册表（JSON 文件）
  - 生成容器卡片"注册"时写入 19081 Hub 的调用指南（doc_md）
  - 供 control 面板（/api/agents/<name>/register）与 19081 Hub（/api/tools）共用

全局参数（使用位置见行内注释）：
"""
import json
import os
import re
import threading
from datetime import datetime, timezone

# TOOLS_REGISTRY_PATH: 注册表 JSON 持久化路径（容器内挂载 /config，宿主机 config/ 目录）
# 使用位置：load_registry / save_registry / *_file 系列函数的默认 path 参数
TOOLS_REGISTRY_PATH = os.environ.get("TOOLS_REGISTRY_PATH", "/config/tools_registry.json")
# _REGISTRY_LOCK: 注册表读写锁，防止多线程并发写坏 JSON
# 使用位置：register_tool_file / unregister_tool_file
_REGISTRY_LOCK = threading.Lock()
# _NAME_SANITIZE_PATTERN: 从容器名派生工具唯一名时清洗非法字符
# 使用位置：derive_tool_name
_NAME_SANITIZE_PATTERN = re.compile(r"[^a-z0-9_-]+")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def derive_tool_name(container_name):
    """从容器名派生工具唯一名称（去掉端口前缀 / hermit-tool- 前缀 / 端口后缀）。"""
    name = (container_name or "").strip()
    name = re.sub(r"^\d+-", "", name)          # 去掉前缀 "19081-"
    name = re.sub(r"^hermit-tool-", "", name)  # 去掉 fork 工具前缀 "hermit-tool-"
    name = re.sub(r"-\d+$", "", name)          # 去掉 fork 工具后缀 "-19082"
    name = name.lower()
    name = _NAME_SANITIZE_PATTERN.sub("-", name).strip("-")
    return name or "tool"


def build_usage_guide(container_name, host_port, agent_type, description=""):
    """生成容器调用指南（Markdown），写入 19081 Hub docs。"""
    display = container_name or "unnamed"
    port_str = str(host_port) if host_port is not None else "未知"
    desc = (description or "").strip() or "%s 容器（%s）" % (agent_type or "unknown", display)
    lines = [
        "# %s" % display,
        "",
        "| 字段 | 值 |",
        "|------|----|",
        "| 容器名称 | `%s` |" % display,
        "| 类型 | `%s` |" % (agent_type or "unknown"),
        "| 宿主机端口 | `%s` |" % port_str,
        "| 访问地址 | http://dimond.top:%s |" % port_str,
        "",
        "## 简介",
        "",
        desc,
        "",
        "## 调用方式",
        "",
        "通过宿主机端口 `%s` 访问该容器提供的服务。" % port_str,
        "",
    ]
    return "\n".join(lines)


def build_tool_record(container_name, host_port, agent_type, description=""):
    """构造完整工具注册记录。"""
    name = derive_tool_name(container_name)
    return {
        "name": name,
        "port": host_port,
        "display_name": container_name,
        "description": (description or "").strip() or "%s 容器（%s）" % (agent_type or "unknown", container_name),
        "doc_md": build_usage_guide(container_name, host_port, agent_type, description),
        "container_name": container_name,
        "agent_type": agent_type,
    }


def normalize_tool_payload(body):
    """把 POST /api/tools 的请求体归一化为工具注册记录（公共接口规范）。

    公共接口（推荐，供 Agent / 容器卡片调用）：
        {
          "container_name": "19082-writer",   # 必填：容器名，派生唯一 name
          "host_port": 19082,                 # 可选：宿主机端口
          "agent_type": "claude",             # 可选：容器类型 claude/ollama/openclaw
          "description": "一句话描述"          # 可选：简介，写入 doc_md
        }

    兼容旧格式（直接传完整记录，原样直通）：
        { "name": "...", "port": 0, "display_name": "...", "description": "...", "doc_md": "..." }
    """
    body = body or {}
    if isinstance(body, dict) and ("container_name" in body or "host_port" in body or "agent_type" in body):
        container_name = str(body.get("container_name") or "").strip()
        if not container_name:
            raise ValueError("container_name is required")
        host_port = body.get("host_port")
        if host_port in (None, ""):
            host_port = None
        agent_type = str(body.get("agent_type") or "unknown")
        description = str(body.get("description") or "")
        return build_tool_record(container_name, host_port, agent_type, description)
    return body


def _default_registry():
    return {"items": {}}


def load_registry(path=None):
    path = path or TOOLS_REGISTRY_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("items"), dict):
            return data
    except Exception:
        pass
    return _default_registry()


def save_registry(registry, path=None):
    path = path or TOOLS_REGISTRY_PATH
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def register_tool(registry, tool):
    """向内存注册表 upsert 一条工具记录（同名覆盖）。"""
    name = (tool or {}).get("name")
    if not name:
        raise ValueError("name is required")
    record = dict(tool)
    record["registered_at"] = record.get("registered_at") or now_iso()
    registry.setdefault("items", {})[name] = record
    return record


def unregister_tool(registry, name):
    return registry.get("items", {}).pop(name, None)


def get_tool(registry, name):
    return registry.get("items", {}).get(name)


def list_tools(registry):
    return sorted(registry.get("items", {}).values(), key=lambda t: t.get("name", ""))


# ---- 文件级便捷封装（自带锁 + 持久化）----

def register_tool_file(tool, path=None):
    with _REGISTRY_LOCK:
        registry = load_registry(path)
        record = register_tool(registry, tool)
        save_registry(registry, path)
        return record


def unregister_tool_file(name, path=None):
    with _REGISTRY_LOCK:
        registry = load_registry(path)
        removed = unregister_tool(registry, name)
        save_registry(registry, path)
        return removed


def get_tool_file(name, path=None):
    return get_tool(load_registry(path), name)


def list_tools_file(path=None):
    return list_tools(load_registry(path))
