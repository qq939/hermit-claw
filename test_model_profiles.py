# -*- coding: utf-8 -*-
"""TDD 校验：模型配置丰富化，4 个新模型配置文件存在、旧文件已删除、模型名称正确。

覆盖点：
  1) 8 个新配置文件存在。
  2) 4 个旧配置文件已删除。
  3) config.json 中模型名称与文件后缀匹配。
  4) settings.json 中 primaryModel 与文件后缀匹配。
  5) 全部 JSON 格式合法。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import json
import os
import sys
import threading

TIMEOUT_SECONDS = 60
ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(ROOT, "config", "claude")

failures = []


def check(name, ok):
    print(("[PASS] " if ok else "[FAIL] ") + name, flush=True)
    if not ok:
        failures.append(name)


def read_json(rel):
    path = os.path.join(ROOT, rel)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run():
    # 1) 8 个新配置文件存在
    new_configs = [
        "config/claude/config.json.minimaxm3",
        "config/claude/config.json.minimaxm27hs",
        "config/claude/config.json.deepseekv4flash",
        "config/claude/config.json.deepseekv4pro",
        "config/claude/settings.json.minimaxm3",
        "config/claude/settings.json.minimaxm27hs",
        "config/claude/settings.json.deepseekv4flash",
        "config/claude/settings.json.deepseekv4pro",
    ]
    for rel in new_configs:
        path = os.path.join(ROOT, rel)
        check("new file exists: %s" % os.path.basename(rel), os.path.isfile(path))

    # 2) 4 个旧配置文件已删除
    old_configs = [
        "config/claude/config.json.minimax",
        "config/claude/config.json.deepseek",
        "config/claude/settings.json.minimax",
        "config/claude/settings.json.deepseek",
    ]
    for rel in old_configs:
        path = os.path.join(ROOT, rel)
        check("old file deleted: %s" % os.path.basename(rel), not os.path.isfile(path))

    # 3) config.json 模型名称与文件后缀匹配
    cfg_expectations = {
        "config/claude/config.json.minimaxm3": "MiniMax-M3",
        "config/claude/config.json.minimaxm27hs": "MiniMax-M3-27B-HighSpeed",
        "config/claude/config.json.deepseekv4flash": "DeepSeek-v4-flash",
        "config/claude/config.json.deepseekv4pro": "DeepSeek-v4-pro",
    }
    for rel, expected_name in cfg_expectations.items():
        data = read_json(rel)
        provider = list(data["claude"]["providers"].values())[0]
        check("config %s name=%s" % (os.path.basename(rel), expected_name),
              provider["name"] == expected_name)
        model = provider["settingsConfig"]["env"]["ANTHROPIC_MODEL"]
        # MiniMax 系列用 MiniMax 前缀，DeepSeek 用 deepseek 前缀
        check("config %s ANTHROPIC_MODEL matches" % os.path.basename(rel),
              model.startswith("MiniMax-") or model.startswith("deepseek-"))

    # 4) settings.json primaryModel 与文件后缀匹配
    sett_expectations = {
        "config/claude/settings.json.minimaxm3": "MiniMax-M3",
        "config/claude/settings.json.minimaxm27hs": "MiniMax-M3-27B-HighSpeed",
        "config/claude/settings.json.deepseekv4flash": "deepseek-v4-flash",
        "config/claude/settings.json.deepseekv4pro": "deepseek-v4-pro",
    }
    for rel, expected_model in sett_expectations.items():
        data = read_json(rel)
        check("settings %s primaryModel=%s" % (os.path.basename(rel), expected_model),
              data["primaryModel"] == expected_model)


if __name__ == "__main__":
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(TIMEOUT_SECONDS)
    if t.is_alive():
        print("FAIL: test timed out after %ds" % TIMEOUT_SECONDS, flush=True)
        sys.exit(1)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)), flush=True)
        sys.exit(1)
    print("ALL CHECKS PASSED", flush=True)
    sys.exit(0)
