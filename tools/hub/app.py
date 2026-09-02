# -*- coding: utf-8 -*-
"""Hermit Tools Hub Flask app（19081 对接文档首页 + /api/tools 接口）。

由 control/app.py 通过 `from tools.hub.app import create_tools_hub_app` 引用，
在 control 容器内监听 8081（宿主机 19081）。
"""
import html

from flask import Flask, jsonify, request

from . import registry

# TOOLS_HUB_PORT_DEFAULT: create_tools_hub_app 首页标题展示的 Hub 端口默认值（可被 control 传入实际端口）
# 使用位置：create_tools_hub_app() 参数默认值
TOOLS_HUB_PORT_DEFAULT = 19081


def create_tools_hub_app(tools_hub_port=TOOLS_HUB_PORT_DEFAULT):
    """19081 工具 Hub（对接文档）：首页展示已注册工具的调用指南，并提供 /api/tools 接口。"""
    hub = Flask("hermit_tools_hub")
    hub.config["JSON_AS_ASCII"] = False

    @hub.get("/api/tools")
    def hub_list():
        return jsonify({"items": registry.list_tools_file()})

    @hub.post("/api/tools")
    def hub_register():
        body = request.get_json(silent=True) or {}
        try:
            record = registry.register_tool_file(body)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify(record), 200

    @hub.get("/api/tools/<name>")
    def hub_get(name):
        record = registry.get_tool_file(name)
        if record is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(record)

    @hub.delete("/api/tools/<name>")
    def hub_delete(name):
        removed = registry.unregister_tool_file(name)
        return jsonify({"ok": True, "removed": bool(removed)})

    @hub.get("/")
    def hub_index():
        items = registry.list_tools_file()
        if not items:
            body = "<p>暂无已注册的工具。可在 Control 面板容器卡片上勾选「注册」写入调用指南。</p>"
        else:
            rows = []
            for t in items:
                name = html.escape(str(t.get("name") or ""))
                display = html.escape(str(t.get("display_name") or name))
                desc = html.escape(str(t.get("description") or ""))
                port = t.get("port")
                doc = html.escape(str(t.get("doc_md") or ""))
                rows.append(
                    f"<section class='tool'>"
                    f"<h2>{display}</h2>"
                    f"<div class='meta'>名称：{name} · 端口：{port} · {desc}</div>"
                    f"<pre>{doc}</pre>"
                    f"</section>"
                )
            body = "\n".join(rows)
        page = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Hermit Tools Hub {tools_hub_port}</title>
<style>
body {{ margin:0; background:#070A10; color:rgba(255,255,255,0.92); font-family:ui-monospace,Menlo,Consolas,monospace; }}
.wrap {{ max-width:1000px; margin:0 auto; padding:24px 18px; }}
h1 {{ font-size:18px; }}
.tool {{ margin-top:16px; border:1px solid rgba(255,255,255,0.14); border-radius:12px; padding:14px; background:linear-gradient(180deg,rgba(255,255,255,0.08),rgba(255,255,255,0.03)); }}
.tool h2 {{ margin:0 0 6px; font-size:15px; }}
.tool .meta {{ color:rgba(255,255,255,0.6); font-size:12px; margin-bottom:10px; }}
pre {{ margin:0; padding:12px; background:rgba(0,0,0,0.3); border-radius:8px; overflow:auto; font-size:12px; line-height:1.4; white-space:pre-wrap; word-break:break-word; }}
</style>
</head>
<body>
<div class="wrap">
<h1>Hermit Tools Hub · 对接文档</h1>
{body}
</div>
</body>
</html>"""
        return page, 200, {"Content-Type": "text/html; charset=utf-8"}

    return hub


def run_hub(tools_hub_port=TOOLS_HUB_PORT_DEFAULT, host="0.0.0.0", port=8081):
    """启动 Hub 服务（阻塞），监听 8081。供 control 进程内线程或独立运行调用。"""
    from werkzeug.serving import make_server

    hub_app = create_tools_hub_app(tools_hub_port)
    server = make_server(host, port, hub_app, threaded=True)
    print("[tools-hub] listening on %d" % port, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    run_hub()
