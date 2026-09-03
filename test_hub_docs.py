# -*- coding: utf-8 -*-
"""TDD 校验：systemreadme 与 hermit-tools-hub skill 对 Hub 公共接口的简略介绍。

覆盖点：
  1) systemreadme 简略介绍 Hub 首页、完整/简化注册格式、统一调用地址 19xxx。
  2) hermit-tools-hub/SKILL.md 介绍所有重要公共接口与示例工具（obs）。
  3) 无旧域名 obs.dimond.top、无 18xxx 端口。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import os
import re
import sys
import threading

TIMEOUT_SECONDS = 60
ROOT = os.path.dirname(os.path.abspath(__file__))

failures = []


def check(name, ok):
    print(("[PASS] " if ok else "[FAIL] ") + name, flush=True)
    if not ok:
        failures.append(name)


def read(rel):
    p = os.path.join(ROOT, rel)
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def run():
    sysreadme = read("config/rules/systemreadme.md")
    skill = read("config/claude/skills/hermit-tools-hub/SKILL.md")

    # 1) systemreadme 简略介绍
    check("systemreadme mentions tools knowledge base", "工具知识库" in sysreadme)
    check("systemreadme mentions full record", "完整记录" in sysreadme)
    check("systemreadme mentions simplified record", "简化记录" in sysreadme)
    check("systemreadme mentions name field", "name" in sysreadme)
    check("systemreadme mentions doc_md", "doc_md" in sysreadme)
    check("systemreadme mentions port field", "port" in sysreadme)
    check("systemreadme uses dimond.top:19xxx", "http://dimond.top:19xxx" in sysreadme)

    # 2) skill 介绍所有重要公共接口 + 示例工具
    for token in ("GET /api/tools", "POST /api/tools",
                  "GET /api/tools/{name}", "DELETE /api/tools/{name}",
                  "/p/{name}/"):
        check("skill mentions %s" % token, token in skill)
    check("skill mentions example tool obs", "obs" in skill and "示例工具" in skill)
    check("skill uses dimond.top:19xxx", "http://dimond.top:19xxx" in skill)

    # 3) 无旧域名 / 18xxx
    check("systemreadme no obs.dimond.top", "obs.dimond.top" not in sysreadme)
    check("skill no obs.dimond.top", "obs.dimond.top" not in skill)
    check("systemreadme no 18xxx", not re.findall(r"18\d{3}", sysreadme))
    check("skill no 18xxx", not re.findall(r"18\d{3}", skill))


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
