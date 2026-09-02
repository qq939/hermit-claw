# -*- coding: utf-8 -*-
"""新增模型配置文件（minimax27hs / deepseekv3flash）的测试脚本（TDD）。

验证：
  - 4 个新配置文件存在且 JSON 有效
  - config.json.minimax27hs 模型名为 MiniMax-M2.7-highspeed，token/base_url 与源一致
  - config.json.deepseekv3flash 模型名为 deepseek-v3-flash，token/base_url 与源一致
  - settings 文件与源完全一致（只改模型名，settings 无模型名字段）

自带超时机制（线程 join 超时）。
"""
import json
import os
import sys
import threading

# Windows 控制台默认编码可能是 cp936/cp1252，强制 stdout 使用 UTF-8，避免中文输出报错
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(ROOT, "config", "claude")

MODEL_KEYS = [
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_MODEL",
]


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def env_of(config):
    providers = config.get("claude", {}).get("providers", {})
    assert providers, "config 缺少 claude.providers"
    for _pid, provider in providers.items():
        return provider.get("settingsConfig", {}).get("env", {})
    raise AssertionError("config 缺少 settingsConfig.env")


def main():
    # --- minimax27hs ---
    src = load(os.path.join(CONFIG_DIR, "config.json.minimax"))
    dst = load(os.path.join(CONFIG_DIR, "config.json.minimax27hs"))
    src_env = env_of(src)
    dst_env = env_of(dst)
    for key in MODEL_KEYS:
        assert dst_env[key] == "MiniMax-M2.7-highspeed", "minimax27hs %s = %s" % (key, dst_env[key])
        assert src_env[key] == "MiniMax-M3", "源 minimax %s 应为 MiniMax-M3，实际 %s" % (key, src_env[key])
    assert dst_env["ANTHROPIC_AUTH_TOKEN"] == src_env["ANTHROPIC_AUTH_TOKEN"], "minimax27hs token 不一致"
    assert dst_env["ANTHROPIC_BASE_URL"] == src_env["ANTHROPIC_BASE_URL"] == "https://api.minimaxi.com/anthropic"

    # --- deepseekv3flash ---
    src = load(os.path.join(CONFIG_DIR, "config.json.deepseek"))
    dst = load(os.path.join(CONFIG_DIR, "config.json.deepseekv3flash"))
    src_env = env_of(src)
    dst_env = env_of(dst)
    for key in MODEL_KEYS:
        assert dst_env[key] == "deepseek-v3-flash", "deepseekv3flash %s = %s" % (key, dst_env[key])
        assert src_env[key] == "deepseek-v4-flash", "源 deepseek %s 应为 deepseek-v4-flash，实际 %s" % (key, src_env[key])
    assert dst_env["ANTHROPIC_AUTH_TOKEN"] == src_env["ANTHROPIC_AUTH_TOKEN"], "deepseekv3flash token 不一致"
    assert dst_env["ANTHROPIC_BASE_URL"] == src_env["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"

    # --- settings 文件应与源完全一致（只复制，不改） ---
    for suffix, src_name in [("minimax27hs", "minimax"), ("deepseekv3flash", "deepseek")]:
        s_new = load(os.path.join(CONFIG_DIR, "settings.json.%s" % suffix))
        s_src = load(os.path.join(CONFIG_DIR, "settings.json.%s" % src_name))
        assert s_new == s_src, "settings.json.%s 与 settings.json.%s 不一致" % (suffix, src_name)

    print("PASS: minimax27hs -> MiniMax-M2.7-highspeed; deepseekv3flash -> deepseek-v3-flash; settings 与源一致")


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
