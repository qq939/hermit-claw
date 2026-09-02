# -*- coding: utf-8 -*-
r"""测试部署脚本对给 agent 看的规范材料（systemreadme / hermit-ports / hermit-tools-hub / hermit-init）
的端口偏移替换逻辑（TDD）。

与 docker-compose.sh（perl）和 docker-compose.ps1（.NET regex）等价的替换规则：
    (?<!\d)18\d{3}(?!\d)  ->  数值 + offset
只替换独立的 5 位 18xxx 端口号，不破坏长数字（时间戳/ID/版本号）。

真实文件的断言基于 git HEAD 基准（18xxx），不依赖工作区当前是否已被替换为 19xxx。
自带超时机制（线程 join 超时）。
"""
import os
import re
import subprocess
import sys
import threading

# Windows 控制台默认编码可能是 cp936/cp1252，强制 stdout 使用 UTF-8，避免中文输出报错
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))

PORT_PATTERN = re.compile(r'(?<!\d)18\d{3}(?!\d)')

RULES_FILES = [
    "config/rules/systemreadme.md",
    "config/claude/skills/hermit-ports/SKILL.md",
    "config/claude/skills/hermit-tools-hub/SKILL.md",
    "config/claude/skills/hermit-init/SKILL.md",
]


def shift_ports(text, offset):
    return PORT_PATTERN.sub(lambda m: str(int(m.group()) + offset), text)


def head_content(rel):
    """读取 git HEAD 中某文件的基准内容（部署脚本先 git checkout 恢复到该状态再替换）。"""
    rel_posix = rel.replace(os.sep, "/")
    out = subprocess.check_output(
        ["git", "show", "HEAD:" + rel_posix],
        cwd=ROOT,
        stderr=subprocess.DEVNULL,
    )
    return out.decode("utf-8")


def main():
    offset = 1000  # start_port 19080 - base 18080

    # --- 单元断言：只替换独立 18xxx，不破坏其它数字 ---
    cases = [
        ("18081", "19081"),
        ("18080", "19080"),
        ("18000-18079", "19000-19079"),
        ("18000-19999", "19000-19999"),
        ("18081-19999", "19081-19999"),
        ("http://host.docker.internal:18081/api/tools", "http://host.docker.internal:19081/api/tools"),
        ("curl http://dimond.top:18000/api/v1/do", "curl http://dimond.top:19000/api/v1/do"),
    ]
    for src, want in cases:
        got = shift_ports(src, offset)
        assert got == want, "shift_ports(%r) = %r, want %r" % (src, got, want)

    # 长数字/非端口数字不应被破坏
    unchanged = [
        "1887123456",                 # 18000 后面仍是数字，非独立端口
        "2026-08-03T14:30:00Z",       # 日期时间
        "1775843188712",              # 毫秒时间戳
        "8082",                       # 内部端口
        "22",                         # SSH 内部端口
        "501",                        # uid
    ]
    for s in unchanged:
        assert shift_ports(s, offset) == s, "不应改动 %r" % s

    # --- 真实文件（基于 git HEAD 基准 18xxx）：替换后无残留且关键端口正确 ---
    contents = {rel: head_content(rel) for rel in RULES_FILES}

    for rel in RULES_FILES:
        src = contents[rel]
        # 基准模板必须含 18xxx 端口（否则替换逻辑无意义）
        assert PORT_PATTERN.search(src), "%s 的 git HEAD 基准缺少 18xxx 端口" % rel
        out = shift_ports(src, offset)
        # 替换后不允许再残留独立的 18xxx
        assert not PORT_PATTERN.search(out), "%s 替换后仍残留 18xxx" % rel

    # --- 关键端口落点抽查 ---
    sysreadme = shift_ports(contents[RULES_FILES[0]], offset)
    assert "19081" in sysreadme, "systemreadme 应出现 19081（原 18081）"
    assert "19000-19999" in sysreadme, "systemreadme 应出现 19000-19999（原 18000-19999）"

    ports_md = shift_ports(contents[RULES_FILES[1]], offset)
    assert "19080" in ports_md, "hermit-ports 应出现 19080（原 18080）"
    assert "19000-19079" in ports_md, "hermit-ports 应出现 19000-19079（原 18000-18079）"
    assert "19081-19999" in ports_md, "hermit-ports 应出现 19081-19999（原 18081-19999）"

    hub_md = shift_ports(contents[RULES_FILES[2]], offset)
    assert "19081" in hub_md, "hermit-tools-hub 应出现 19081（原 18081）"
    assert "19000" in hub_md, "hermit-tools-hub 应出现 19000（原 18000）"

    init_md = shift_ports(contents[RULES_FILES[3]], offset)
    assert "19081" in init_md, "hermit-init 应出现 19081（原 18081）"

    print("PASS: 规范材料端口偏移替换逻辑正确（offset=1000，覆盖 4 个真实文件）")


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
