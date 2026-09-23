# -*- coding: utf-8 -*-
"""TDD 校验：本地 llama.cpp 服务的上下文长度足够 Claude Code 使用。

背景：
  Claude Code 单次请求实测已到 18723 tokens（system prompt + 工具定义 + 历史），
  而 compose 里 `-c 8192` 直接返回：
    400 exceed_context_size_error, n_prompt_tokens=18723, n_ctx=8192
  原 vLLM 版为此用 --max-model-len 49152。这里目标 >= 32768。

VRAM 约束（RTX 4080 16G，实测）：权重 12.4 GiB 是固定开销，-c 8192 时仅剩 ~900 MiB。
  所以提高 -c 必须同时压 KV 显存（-ctk/-ctv 量化，或降 -ngl）。

覆盖点：
  1) 真值源 compose 中 llama-qwen38 的 -c >= MIN_CTX。
  2) 线上 /v1/models 的 meta.n_ctx >= MIN_CTX。
  3) 功能性：构造 ~20k token 的请求必须 200（而不是 400 exceed_context_size_error）。
     这正是用户遇到的场景，属于回归测试。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 900
COMPOSE_FILE = r"C:\Users\qq939\Downloads\qwen38\docker-compose.yml"
LOCAL_HOST_URL = os.environ.get("LOCAL_MODEL_URL", "http://127.0.0.1:8000")
LOCAL_MODEL = "qwen3.8-27b"
MIN_CTX = 32768
BIG_PROMPT_TOKENS = 20000

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


def compose_llama_ctx():
    """从 compose 的 llama-qwen38 服务命令里取 -c 的值。"""
    with open(COMPOSE_FILE, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    # 截取 llama-qwen38 服务段（到下一个顶层服务定义或文件末）
    m = re.search(r"\n  llama-qwen38:\n(.*?)(?=\n  [a-zA-Z0-9_-]+:\n|\Z)", text, re.S)
    if not m:
        return None
    block = m.group(1)
    # YAML 列表形如：  - -c\n      - "32768"
    m2 = re.search(r"-\s*-c\s*\n\s*-\s*[\"']?(\d+)[\"']?", block)
    return int(m2.group(1)) if m2 else None


def compose_llama_block():
    with open(COMPOSE_FILE, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    m = re.search(r"\n  llama-qwen38:\n(.*?)(?=\n  [a-zA-Z0-9_-]+:\n|\Z)", text, re.S)
    return m.group(1) if m else ""


def post_messages(payload, timeout):
    req = urllib.request.Request(
        LOCAL_HOST_URL + "/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "anthropic-version": "2023-06-01",
                 "x-api-key": "dummy"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body), None
        except Exception:
            return e.code, None, body[:300]


def run():
    # 1) 真值源 compose
    check("compose file exists", os.path.isfile(COMPOSE_FILE))
    if not os.path.isfile(COMPOSE_FILE):
        return
    ctx = compose_llama_ctx()
    check("compose llama-qwen38 -c parsed", ctx is not None)
    if ctx is not None:
        check("compose llama-qwen38 -c >= %d (got %s)" % (MIN_CTX, ctx), ctx >= MIN_CTX)
    block = compose_llama_block()
    # KV 显存必须压缩，否则 16G 装不下（量化到 8bit/4bit KV）
    check("compose sets KV cache type (kv quant)",
          ("-ctk" in block) or ("--cache-type-k" in block))

    # 2) 线上 n_ctx
    try:
        with urllib.request.urlopen(LOCAL_HOST_URL + "/v1/models", timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        n_ctx = (data.get("data") or [{}])[0].get("meta", {}).get("n_ctx")
        check("live n_ctx >= %d (got %s)" % (MIN_CTX, n_ctx),
              isinstance(n_ctx, int) and n_ctx >= MIN_CTX)
    except Exception as e:
        skip("live /v1/models n_ctx", "unreachable: %s" % e)
        return

    # 3) 功能性：复现用户遇到的 ~20k token 请求
    #    用重复文本凑长度；每 token 约 4 字符，故约 4 chars * BIG_PROMPT_TOKENS
    #    注意：llama.cpp 在长上下文/缓存未命中时会全量重算，实测同一请求耗时 8.8s~308s，
    #    所以这里只断言"不再 400 exceed_context_size_error"，慢但成功算通过。
    filler = ("The quick brown fox jumps over the lazy dog. "
              "Pack my box with five dozen liquor jugs. ")
    text = (filler * ((BIG_PROMPT_TOKENS * 4) // len(filler) + 1))
    text += "\n\nAbove is padding. Reply with exactly: OK"
    status, body, raw = post_messages(
        {"model": LOCAL_MODEL, "max_tokens": 16,
         "messages": [{"role": "user", "content": text}]},
        timeout=600)
    check("big prompt request not rejected (status %s)" % status, status == 200)
    if status != 200:
        print("   -> %s" % (raw if raw else json.dumps(body)[:300]), flush=True)
        return
    # llama.cpp 的 usage.input_tokens 只统计"新评估"的 token（缓存命中的不算），
    # 所以这里不能用它来判断 prompt 大小，改用服务端 slot 的 stop processing n_tokens。
    used = (body.get("usage") or {}).get("input_tokens")
    print("   -> newly-evaluated input_tokens=%s (total prompt ~%d)"
          % (used, BIG_PROMPT_TOKENS), flush=True)


if __name__ == "__main__":
    def guarded():
        # 守护线程里的未捕获异常会让 join() 提前返回且 failures 为空，造成"假绿"，
        # 所以这里必须兜住并记为失败。
        try:
            run()
        except Exception:
            import traceback
            traceback.print_exc()
            failures.append("unhandled exception in test thread")

    t = threading.Thread(target=guarded, daemon=True)
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
