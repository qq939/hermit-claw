# docker-compose.ps1
# Hermit 部署脚本：
#   1) 从 config/hermit_settings.json 读取起始端口 start_port
#   2) 恢复 docker-compose.yml 为默认占位状态（18080）
#   3) 将 docker-compose.yml 中的 18080 动态替换为 start_port
#   4) 执行 docker compose 部署 control 服务
# 说明：端口来自配置文件，不硬编码，修改 hermit_settings.json 后重新运行即可生效。

$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$settingsPath = Join-Path $root "config/hermit_settings.json"
$composePath = Join-Path $root "docker-compose.yml"

# 1. 读取配置端口
if (-not (Test-Path $settingsPath)) {
    Write-Error "配置文件不存在: $settingsPath"
    exit 1
}
$settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
$port = $settings.start_port
if (-not $port) {
    Write-Error "hermit_settings.json 中缺少 start_port 字段"
    exit 1
}
Write-Host "目标起始端口: $port"

# 2. 恢复 docker-compose.yml 为默认占位（18080），保证脚本可重复执行
git -C $root checkout -- docker-compose.yml 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "警告: git checkout 恢复 docker-compose.yml 失败，使用当前文件继续"
}

# 3. 将 18080 动态替换为目标端口（service 名 / container_name / ports 映射）
$content = [System.IO.File]::ReadAllText($composePath)
$newContent = $content.Replace("18080", "$port")
[System.IO.File]::WriteAllText($composePath, $newContent, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "已将 docker-compose.yml 中的 18080 替换为 $port"

# 4. 部署 control 服务
Write-Host "开始部署 control-$port 服务..."
docker compose up -d --build "control-$port"
if ($LASTEXITCODE -ne 0) {
    Write-Error "docker compose 部署失败"
    exit 1
}
Write-Host "部署完成，控制面板访问地址: http://localhost:$port"
