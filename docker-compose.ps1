# docker-compose.ps1
# Hermit 部署脚本：端口已固定为 19xxx（19080 控制面板 / 19081 工具 Hub）。
# 脚本不再做任何字符串替换或端口偏移，直接部署 docker-compose.yml 中已写好的 control-19080 服务。

$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
Set-Location $root

# 显式把 PWD 指向本仓库根目录：compose 里的 ${PWD} 取的是这个环境变量，
# 从别的目录调用本脚本（例如在 DSH checkout 里）若不设置，会把宿主机路径烤错，
# 导致之后新建/重建的卡片挂到错误甚至空的目录上（实测踩过）。
$env:PWD = ($root -replace '\\', '/')

# 部署 control 服务（docker-compose.yml 已固定 control-19080: 19080/19081 端口映射）
docker compose up -d --build control-19080
if ($LASTEXITCODE -ne 0) {
    Write-Error "docker compose 部署失败"
    exit 1
}

Write-Host "部署完成，控制面板访问地址: http://localhost:19080"
Write-Host "工具 Hub 对接文档: http://localhost:19081"
