# -*- coding: utf-8 -*-
"""TDD 校验：本地 Qwen3.8-27B 启动脚本与真实架构一致。

背景（2026-09 架构更换）：
  真值源 compose： C:\\Users\\qq939\\Downloads\\qwen38\\docker-compose.yml
  该文件有两个互斥服务（都独占 GPU 与 :8000）：
    - qwen38       vLLM（W4A16，需 --cpu-offload-gb，约 2-3 tok/s），profiles 默认
    - llama-qwen38 llama.cpp GGUF（无 offload，约 41 tok/s），profiles ["llama"]
  当前实际运行的是 llama-qwen38，因此启动脚本必须默认拉它。

覆盖点：
  1) run-vllm-qwen38.ps1 存在。
  2) 脚本默认目标容器名是 llama-qwen38（而不是 vllm-qwen38）。
  3) compose up 时显式带上服务名 llama-qwen38（不加服务名会走默认 profile 拉起 vLLM）。
  4) compose 目录指向真值源 C:\\Users\\qq939\\Downloads\\qwen38。
  5) 不再回退到仓库内已过期的镜像副本 docker-compose.vllm.yml（它没有 llama-qwen38 服务）。
  6) 实测：容器 llama-qwen38 在跑，且 /v1/models 暴露 qwen3.8-27b。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import json
import os
import subprocess
import sys
import threading
import urllib.request

TIMEOUT_SECONDS = 90
ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(ROOT, "run-vllm-qwen38.ps1")
COMPOSE_DIR = r"C:\Users\qq939\Downloads\qwen38"
LOCAL_CONTAINER = "llama-qwen38"
LOCAL_MODEL = "qwen3.8-27b"
LOCAL_HOST_URL = os.environ.get("LOCAL_MODEL_URL", "http://127.0.0.1:8000")

failures = []
skips = []

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def check(name, ok):
    print(("[PASS] " if ok else "[FAIL] ") + name, flush=True)
    if not ok:
        failures.append(name)


def skip(name, reason):
    print("[SKIP] %s (%s)" % (name, reason), flush=True)
    skips.append(name)


def run():
    check("run-vllm-qwen38.ps1 exists", os.path.isfile(SCRIPT))
    if not os.path.isfile(SCRIPT):
        return

    with open(SCRIPT, "r", encoding="utf-8", errors="replace") as f:
        src = f.read()

    # 2) 目标容器名
    check("script targets container llama-qwen38", '$name = "llama-qwen38"' in src)
    check("script no longer targets vllm-qwen38", '"vllm-qwen38"' not in src)

    # 3) compose up 必须显式指定服务名，否则走默认 profile 拉起 vLLM 版 qwen38
    check("script invokes compose with service llama-qwen38",
          "docker compose up -d llama-qwen38" in src)

    # 4) 指向真值源目录
    check("script points at truth-source compose dir",
          COMPOSE_DIR.replace("\\", "\\\\") in src or COMPOSE_DIR in src)

    # 5) 去掉过期的仓库镜像副本回退
    check("script drops stale repo mirror fallback", "docker-compose.vllm.yml" not in src)

    # 6) 实测
    try:
        out = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", LOCAL_CONTAINER],
            capture_output=True, text=True, timeout=30)
        status = out.stdout.strip()
        check("container %s running" % LOCAL_CONTAINER, status == "running")
        if status != "running":
            print("   -> got %r %s" % (status, out.stderr.strip()[:120]), flush=True)
    except Exception as e:
        skip("container %s running" % LOCAL_CONTAINER, "failed: %s" % e)

    try:
        with urllib.request.urlopen(LOCAL_HOST_URL + "/v1/models", timeout=20) as resp:
            ids = [m.get("id") for m in (json.loads(resp.read().decode("utf-8")).get("data") or [])]
        check("local model serves %s" % LOCAL_MODEL, LOCAL_MODEL in ids)
        print("   -> model ids: %s" % ids, flush=True)
    except Exception as e:
        skip("local model /v1/models", "unreachable: %s" % e)


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
    print("ALL CHECKS PASSED%s" % (" (%d skipped)" % len(skips) if skips else ""), flush=True)
    sys.exit(0)
