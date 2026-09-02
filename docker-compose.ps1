# docker-compose.ps1
# Hermit deployment script (Windows):
#   1) Read start_port from config/hermit_settings.json
#   2) Restore docker-compose.yml to its default placeholder state (base 18080)
#   3) Rewrite ALL host-side 18xxx ports by PORT_OFFSET = start_port - 18080.
#      Container-internal ports (8080 / 8088 / 5030 / 18790 / 22) are NOT changed.
#   4) Build agent template images (they use profiles: ["templates"], not built by `up`)
#   5) Run docker compose to deploy the control service
# Notes: ports come from the config file, nothing is hard-coded here.

$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$settingsPath = Join-Path $root "config/hermit_settings.json"
$composePath = Join-Path $root "docker-compose.yml"

# 1. Read configured start port
if (-not (Test-Path $settingsPath)) {
    Write-Error "Config file not found: $settingsPath"
    exit 1
}
$settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
$port = [int]$settings.start_port
if (-not $port) {
    Write-Error "Missing start_port in hermit_settings.json"
    exit 1
}
Write-Host "Target start port: $port"

# 2. Restore docker-compose.yml to default placeholders (keeps runs repeatable)
git -C $root checkout -- docker-compose.yml 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Warning: git checkout failed to restore docker-compose.yml, continuing with current file"
}

# 3. Rewrite all host-side 18xxx ports by offset
$base = 18080
$offset = $port - $base

# host-side ports that must follow the offset
$map = [ordered]@{
    "18080" = [string](18080 + $offset)  # control panel: service / container / host port
    "18000" = [string](18000 + $offset)  # obs tool: service / container / host port / HOST_PORT
    "18001" = [string](18001 + $offset)  # email tool: service / container / host port / HOST_PORT
    "18081" = [string](18081 + $offset)  # tools hub: TOOLS_HUB_URL
    "18800" = [string](18800 + $offset)  # ssh gateway host port
}
$gatewayHost = [string](18790 + $offset)  # openclaw gateway: host side only (container side stays 18790)

$content = [System.IO.File]::ReadAllText($composePath)

# openclaw-gateway port mapping: change host side, keep container side 18790
$content = $content.Replace('"18790:18790"', ('"' + $gatewayHost + ':18790"'))

foreach ($key in $map.Keys) {
    $content = $content.Replace($key, $map[$key])
}

[System.IO.File]::WriteAllText($composePath, $content, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "Rewrote docker-compose.yml host ports (offset=$offset)"

# 4. Build agent template images (profiles: ["templates"] are not built by `up`)
Write-Host "Building agent template images..."
docker compose build agent-image-claude agent-image-openclaw agent-image-ollama
if ($LASTEXITCODE -ne 0) {
    Write-Error "Agent template image build failed"
    exit 1
}

# 5. Deploy control service
Write-Host "Deploying control-$port ..."
docker compose up -d --build "control-$port"
if ($LASTEXITCODE -ne 0) {
    Write-Error "docker compose deploy failed"
    exit 1
}
Write-Host "Done. Control panel: http://localhost:$port"
