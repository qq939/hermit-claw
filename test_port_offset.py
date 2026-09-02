# -*- coding: utf-8 -*-
"""端口偏移替换逻辑的测试脚本（TDD）。

验证 docker-compose.sh / docker-compose.ps1 的端口偏移替换策略：
  - 从 config/hermit_settings.json 读取 start_port
  - 按 offset = start_port - 18080 重写所有 18xxx 宿主机端口
  - 容器内部端口（8080/8088/5030/18790）保持不变

自带超时机制（线程 join 超时），避免测试卡死。
"""
import json
import os
import re
import sys
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))


def apply_replacements(content, start_port):
    """与 docker-compose.sh / docker-compose.ps1 完全一致的替换逻辑。"""
    base = 18080
    offset = start_port - base
    gateway_host = 18790 + offset

    # 只改 openclaw-gateway 宿主侧，容器侧 18790 保持不变
    content = content.replace('"18790:18790"', '"{}:18790"'.format(gateway_host))

    mapping = {
        "18080": str(18080 + offset),  # 控制面
        "18000": str(18000 + offset),  # obs 工具
        "18001": str(18001 + offset),  # email 工具
        "18081": str(18081 + offset),  # 工具 Hub
        "18800": str(18800 + offset),  # ssh 网关
    }
    for key, val in mapping.items():
        content = content.replace(key, val)
    return content


def main():
    settings_path = os.path.join(ROOT, "config", "hermit_settings.json")
    with open(settings_path, encoding="utf-8") as f:
        settings = json.load(f)
    start_port = int(settings["start_port"])
    offset = start_port - 18080
    assert offset != 0, "start_port 不应等于基准 18080"

    compose_path = os.path.join(ROOT, "docker-compose.yml")
    with open(compose_path, encoding="utf-8") as f:
        template = f.read()

    # 模板必须处于基准 18080 状态
    assert '"18080:8080"' in template, "模板应包含控制面宿主映射 18080:8080"
    assert '"18790:18790"' in template, "模板应包含 openclaw-gateway 映射"
    assert "OPENCLAW_GATEWAY_PORT=18790" in template, "模板应包含网关容器侧端口"

    result = apply_replacements(template, start_port)

    control = str(18080 + offset)
    obs = str(18000 + offset)
    email = str(18001 + offset)
    hub = str(18081 + offset)
    ssh = str(18800 + offset)
    gw = str(18790 + offset)

    # 控制面
    assert '"%s:8080"' % control in result, "控制面宿主端口错误"
    assert "control-%s" % control in result, "控制面 service 名错误"
    assert "hermit-control-%s" % control in result, "控制面 container 名错误"
    # obs 工具
    assert '"%s:8088"' % obs in result, "obs 宿主端口错误"
    assert "obs-%s" % obs in result, "obs service 名错误"
    assert "hermit-tool-obs-%s" % obs in result, "obs container 名错误"
    assert "HOST_PORT=%s" % obs in result, "obs HOST_PORT 错误"
    # email 工具
    assert '"%s:5030"' % email in result, "email 宿主端口错误"
    assert "email-%s" % email in result, "email service 名错误"
    assert "hermit-tool-email-%s" % email in result, "email container 名错误"
    assert "HOST_PORT=%s" % email in result, "email HOST_PORT 错误"
    # 工具 Hub
    assert "TOOLS_HUB_URL=http://host.docker.internal:%s" % hub in result, "工具 Hub 端口错误"
    # ssh 网关
    assert '"%s:8080"' % ssh in result, "ssh 网关宿主端口错误"
    # openclaw 网关：宿主侧偏移，容器侧保持 18790
    assert '"%s:18790"' % gw in result, "openclaw-gateway 宿主端口错误"
    assert "OPENCLAW_GATEWAY_PORT=18790" in result, "openclaw-gateway 容器侧端口被误改"

    # 除容器侧 18790 外，不应残留任何 18xxx 宿主机端口
    stale = [s for s in re.findall(r"18[0-9]{3}", result) if s != "18790"]
    assert not stale, "残留 18xxx 宿主机端口: %s" % stale

    # 容器内部端口保持不变
    assert ":8080" in result and ":8088" in result and ":5030" in result and ":18790" in result

    print(
        "PASS start_port=%s offset=%s -> control=%s obs=%s email=%s hub=%s ssh=%s gateway_host=%s"
        % (start_port, offset, control, obs, email, hub, ssh, gw)
    )


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
