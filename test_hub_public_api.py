# -*- coding: utf-8 -*-
r"""Hub 公共接口抽象 + systemreadme 注册说明的 TDD 测试（纯标准库，自带超时机制）。

验证：
  - tools/hub/registry.py 抽象出 normalize_tool_payload 公共接口，把
    container_name / host_port / agent_type / description 归一化为完整工具记录；
  - tools/hub/app.py 的 POST /api/tools 使用该公共接口；
  - systemreadme.md 与 hermit-tools-hub/SKILL.md 写明「如何到 Hub 注册」及公共字段。
"""
import os
import sys
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


def main():
    from tools.hub import registry

    # --- 1. registry 抽象出公共接口 ---
    assert hasattr(registry, "normalize_tool_payload"), "registry 应抽象出 normalize_tool_payload 公共接口"
    assert hasattr(registry, "build_tool_record"), "registry 应保留 build_tool_record"

    # --- 2. 公共字段归一化为完整记录 ---
    payload = {
        "container_name": "19082-writer",
        "host_port": 19082,
        "agent_type": "claude",
        "description": "写作工具",
    }
    record = registry.normalize_tool_payload(payload)
    assert record["name"] == "writer", "container_name 应派生 name=writer，实际=%r" % record.get("name")
    assert record["port"] == 19082, "host_port 应映射为 port"
    assert record["agent_type"] == "claude", "agent_type 应透传"
    assert record["container_name"] == "19082-writer", "container_name 应透传"
    assert "写作工具" in record["doc_md"], "description 应写入 doc_md"

    # --- 3. 缺 container_name 应报错 ---
    try:
        registry.normalize_tool_payload({"host_port": 19082})
    except ValueError:
        pass
    else:
        raise AssertionError("缺 container_name 应抛出 ValueError")

    # --- 4. host_port 缺省时不应崩溃，port 记为空 ---
    no_port = registry.normalize_tool_payload({"container_name": "19083-painter", "agent_type": "ollama"})
    assert no_port["name"] == "painter"
    assert no_port["agent_type"] == "ollama"

    # --- 5. 兼容旧格式（完整记录直通）---
    legacy = {"name": "legacy", "port": 1, "display_name": "legacy", "doc_md": "x"}
    assert registry.normalize_tool_payload(legacy) == legacy, "旧格式完整记录应原样直通"

    # --- 6. app.py 的 POST /api/tools 使用公共接口 ---
    app_src = read("tools/hub/app.py")
    assert "normalize_tool_payload" in app_src, "app.py 的 POST /api/tools 应调用 normalize_tool_payload"

    # --- 7. systemreadme.md 写明如何到 Hub 注册 + 公共字段 ---
    readme = read("config/rules/systemreadme.md")
    assert "POST http://host.docker.internal:18081/api/tools" in readme, "systemreadme 应写明 POST /api/tools 注册接口"
    assert "container_name" in readme, "systemreadme 应说明 container_name 字段"
    assert "host_port" in readme, "systemreadme 应说明 host_port 字段"
    assert "agent_type" in readme, "systemreadme 应说明 agent_type 字段"
    assert "注册" in readme, "systemreadme 应包含注册说明"

    # --- 8. hermit-tools-hub/SKILL.md 引用公共接口规范 ---
    skill = read("config/claude/skills/hermit-tools-hub/SKILL.md")
    assert "container_name" in skill, "SKILL 应说明 container_name 公共字段"
    assert "host_port" in skill, "SKILL 应说明 host_port 公共字段"
    assert "agent_type" in skill, "SKILL 应说明 agent_type 公共字段"

    print("PASS: Hub 公共接口抽象 + systemreadme 注册说明正确")


if __name__ == "__main__":
    TIMEOUT = 30
    errors = {}

    def run():
        try:
            main()
        except Exception as exc:  # noqa: BLE001
            errors["e"] = exc

    worker = threading.Thread(target=run)
    worker.start()
    worker.join(TIMEOUT)
    if worker.is_alive():
        print("FAIL: 测试超时（%ds）" % TIMEOUT)
        sys.exit(1)
    if errors:
        print("FAIL:", errors["e"])
        sys.exit(1)
    print("ALL TESTS PASSED")
