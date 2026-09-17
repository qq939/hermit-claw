# -*- coding: utf-8 -*-
"""TDD 校验：control 面板首页 JS 语法健康（捕获 f-string 把 \\n 转成真实换行导致的 JS 语法错误）。

背景：control/app.py 的 index() 用 Python f-string 生成 HTML+JS。
若在 JS 单引号字符串里写 '\n'（单反斜杠），Python 会把它变成真实换行，
生成出跨行的字符串字面量，导致整个 <script> 语法错误、面板空白。

覆盖点：
  1) 静态：control/app.py 的 index() f-string 区内，不存在会退化成真实换行的 \\n。
  2) 动态：抓取已部署的 http://localhost:19080/ ，扫描所有 <script>，
     检测单/双引号字符串是否跨行（跨行即 JS 语法错误）。
     —— 服务不可达时标记 SKIP，不误报。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import os
import re
import sys
import threading
import urllib.request

TIMEOUT_SECONDS = 60
ROOT = os.path.dirname(os.path.abspath(__file__))
CONTROL_URL = os.environ.get("CONTROL_URL", "http://localhost:19080/")

failures = []
skips = []

# Windows 控制台默认 cp1252，避免打印中文/非 ASCII 时崩溃
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


def scan_script(src):
    """扫描 JS 源码，返回跨行单/双引号字符串的行号列表（即语法错误点）。"""
    errors = []
    i = 0
    n = len(src)
    line = 1
    state = None          # None | "'" | '"' | '`'
    escape = False
    while i < n:
        ch = src[i]
        if ch == "\n":
            if state in ("'", '"'):
                errors.append(line)
            line += 1
            escape = False
            i += 1
            continue
        if state is None:
            if not escape:
                if ch in ("'", '"', "`"):
                    state = ch
                elif ch == "/" and i + 1 < n and src[i + 1] == "/":
                    # 行注释：跳到行尾
                    while i < n and src[i] != "\n":
                        i += 1
                    continue
                elif ch == "/" and i + 1 < n and src[i + 1] == "*":
                    i += 2
                    while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                        if src[i] == "\n":
                            line += 1
                        i += 1
                    i += 2
                    continue
        else:
            if not escape:
                if ch == "\\":
                    escape = True
                    i += 1
                    continue
                if ch == state:
                    state = None
                    i += 1
                    continue
        escape = False
        i += 1
    return errors


def extract_scripts(html):
    return re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL | re.IGNORECASE)


def scan_js_bad_escape(js):
    """扫描 JS 源码，找出「Python 会退化成真实换行」的 \\n。

    只关心 JS 单/双引号字符串里的 \\n（会导致字符串跨行 → 语法错误）。
    反引号模板字符串允许跨行，不报。注释不扫描。
    返回 [(行号, 行内容)]。
    """
    bad = []
    state = None      # None | "'" | '"' | '`'
    line_no = 1
    cur = []
    i = 0
    n = len(js)
    while i < n:
        ch = js[i]
        if ch == "\n":
            if state in ("'", '"'):
                bad.append((line_no, "".join(cur).strip()[:110]))
            line_no += 1
            cur = []
            i += 1
            continue
        cur.append(ch)
        if state is None:
            if ch in ("'", '"', "`"):
                state = ch
            elif ch == "/" and i + 1 < n and js[i + 1] == "/":
                while i < n and js[i] != "\n":
                    i += 1
                continue
            elif ch == "/" and i + 1 < n and js[i + 1] == "*":
                i += 2
                while i + 1 < n and not (js[i] == "*" and js[i + 1] == "/"):
                    if js[i] == "\n":
                        line_no += 1
                    i += 1
                i += 2
                continue
        elif state == "`":
            if ch == "\\":
                i += 1
                if i < n:
                    cur.append(js[i])
            elif ch == "`":
                state = None
        else:  # "'" or '"'
            if ch == "\\":
                nxt = js[i + 1] if i + 1 < n else ""
                if nxt == "n":
                    bad.append((line_no, "".join(cur).strip()[:110]))
                i += 1
                if i < n:
                    cur.append(js[i])
            elif ch == state:
                state = None
        i += 1
    return bad


def run():
    # ---- 0) 检测器自检：必须能抓到真实的错误写法，且不误报安全写法 ----
    # 注意：这里传入的是「源码形态」（即 Python 源码里写的样子）。
    check("detector flags broken join",
          scan_js_bad_escape("x.join('\\n')") != [])
    check("detector flags broken prompt",
          scan_js_bad_escape("prompt('a:\\n' + b)") != [])
    check("detector allows escaped join",
          scan_js_bad_escape("x.join('\\\\n')") == [])
    check("detector allows template literal",
          scan_js_bad_escape("x += `\\nhi\\n`") == [])

    # ---- 1) 静态检查：index() 的 f-string 区内不得有会退化成真实换行的 \n ----
    src_path = os.path.join(ROOT, "control", "app.py")
    with open(src_path, "r", encoding="utf-8") as f:
        app = f.read()

    end = app.index("return make_response(html)")
    start = app.rindex('html = f"""', 0, end)
    region = app[start:end]
    check("index f-string located", start > 0 and start < end)

    # 危险写法：JS 单/双引号字符串里的 \n（Python 会输出真实换行 → 字符串跨行 → 语法错误）。
    # 只扫 <script> 区块，避免 HTML/CSS 中的撇号干扰引号状态。
    src_scripts = extract_scripts(region)
    check("index f-string has script blocks", len(src_scripts) > 0)
    base_line = app[:start].count("\n") + 1
    offenders = []
    for js in src_scripts:
        for ln, txt in scan_js_bad_escape(js):
            offenders.append("L~%d: %s" % (base_line + ln - 1, txt))
    check("no raw \\n in JS quoted string of index f-string", not offenders)
    for o in offenders[:10]:
        print("   -> %s" % o, flush=True)

    # ---- 2) 动态检查：抓线上页面，扫描 script 跨行字符串 ----
    try:
        with urllib.request.urlopen(CONTROL_URL, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        skip("live control page scanned", "unreachable: %s" % e)
        return

    scripts = extract_scripts(html)
    check("live page has inline scripts", len(scripts) > 0)

    bad_lines = []
    for idx, s in enumerate(scripts):
        errs = scan_script(s)
        if errs:
            bad_lines.append("script#%d lines %s" % (idx, errs[:5]))
    check("live page has no cross-line JS string literal", not bad_lines)
    for b in bad_lines:
        print("   -> %s" % b, flush=True)

    # 附带：关键 UI 元素必须存在（面板正常渲染的前提）
    check("live page has register-btn", "register-btn" in html)
    check("live page has port-btn", "port-btn" in html)
    check("live page has makeCard", "makeCard" in html)


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
