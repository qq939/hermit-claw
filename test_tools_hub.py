# -*- coding: utf-8 -*-
"""tools/hub/registry.py 的 TDD 测试（纯标准库，自带超时机制）。

验证：
  - derive_tool_name 从容器名派生工具唯一名
  - build_tool_record / build_usage_guide 生成调用指南（doc_md）
  - 注册表 register / unregister / get / list 的 upsert 语义
  - 文件级便捷封装（register_tool_file / unregister_tool_file）持久化
"""
import os
import sys
import tempfile
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from tools.hub import registry as tools_hub  # noqa: E402


def main():
    # --- derive_tool_name ---
    assert tools_hub.derive_tool_name("19081-writer") == "writer"
    assert tools_hub.derive_tool_name("hermit-tool-obs-19000") == "obs"
    assert tools_hub.derive_tool_name("hermit-tool-writer-19082") == "writer"
    assert tools_hub.derive_tool_name("") == "tool"
    assert tools_hub.derive_tool_name(None) == "tool"

    # --- build_tool_record / build_usage_guide ---
    rec = tools_hub.build_tool_record("19081-writer", 19081, "claude")
    assert rec["name"] == "writer"
    assert rec["port"] == 19081
    assert rec["container_name"] == "19081-writer"
    assert rec["agent_type"] == "claude"
    guide = rec["doc_md"]
    assert "19081" in guide, "调用指南应包含宿主机端口"
    assert "claude" in guide, "调用指南应包含类型"
    assert "writer" in guide, "调用指南应包含容器名"
    assert guide.strip().startswith("# "), "调用指南应为 Markdown 标题开头"

    # --- 注册表 upsert 语义 ---
    registry = {"items": {}}
    tools_hub.register_tool(registry, rec)
    assert tools_hub.get_tool(registry, "writer") is not None
    assert len(tools_hub.list_tools(registry)) == 1

    # 同名覆盖，不新增
    rec2 = tools_hub.build_tool_record("19081-writer", 19081, "claude", description="更新后的描述")
    tools_hub.register_tool(registry, rec2)
    assert len(tools_hub.list_tools(registry)) == 1
    assert tools_hub.get_tool(registry, "writer")["description"] == "更新后的描述"

    # 缺少 name 报错
    try:
        tools_hub.register_tool(registry, {"port": 1})
        raise AssertionError("缺少 name 应抛 ValueError")
    except ValueError:
        pass

    # unregister
    removed = tools_hub.unregister_tool(registry, "writer")
    assert removed is not None
    assert tools_hub.get_tool(registry, "writer") is None
    assert tools_hub.unregister_tool(registry, "writer") is None

    # --- 文件级封装：持久化 roundtrip ---
    tmp = tempfile.mktemp(suffix=".json")
    try:
        r1 = tools_hub.register_tool_file(
            tools_hub.build_tool_record("19082-email", 19082, "ollama"), path=tmp
        )
        assert tools_hub.get_tool_file("email", path=tmp) is not None
        listed = tools_hub.list_tools_file(path=tmp)
        assert any(t["name"] == "email" for t in listed)
        # 再次加载确认已落盘
        assert tools_hub.get_tool_file("email", path=tmp)["port"] == 19082
        removed2 = tools_hub.unregister_tool_file("email", path=tmp)
        assert removed2 is not None
        assert tools_hub.get_tool_file("email", path=tmp) is None
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    print("PASS: tools_hub 注册表与调用指南逻辑正确")


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
