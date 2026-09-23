# run-vllm-qwen38.ps1
# 拉起本地 vLLM（Qwen3.8-27B W4A16），供 hermit 的 localqwen profile 使用。
#
# 真值源（模型与 compose 同目录）：
#     C:\Users\qq939\Downloads\qwen38\docker-compose.yml
# 本脚本只是"切到该目录 → docker compose up -d → 等 /v1/models 就绪"的薄封装。
# 参数为什么是这些，见那个 compose 文件里的注释（tool-choice / qwen3_xml / 49152 / fp8 / cpu-offload）。
#
# 用法： .\run-vllm-qwen38.ps1
# 就绪： curl http://localhost:8000/v1/models  → qwen3.8-27b

$ErrorActionPreference = "Stop"

$composeDir = "C:\Users\qq939\Downloads\qwen38"
$composeFile = Join-Path $composeDir "docker-compose.yml"
$name = "vllm-qwen38"

if (-not (Test-Path $composeFile)) {
    # 回退：仓库内镜像副本（仅作参考，正常应使用 qwen38 目录里的那份）
    $fallback = Join-Path $PSScriptRoot "docker-compose.vllm.yml"
    if (-not (Test-Path $fallback)) {
        Write-Error "找不到 compose 文件：$composeFile"
        exit 1
    }
    Write-Warning "未找到 $composeFile，回退到仓库副本 $fallback"
    $composeDir = $PSScriptRoot
    $composeFile = $fallback
}

Write-Host "compose: $composeFile"
Push-Location $composeDir
try {
    docker compose up -d
    if ($LASTEXITCODE -ne 0) {
        Write-Error "docker compose up 失败"
        exit 1
    }
} finally {
    Pop-Location
}

Write-Host "容器已启动，首次加载权重约 2-4 分钟（27B W4A16 + 8G 权重卸载到 CPU）..."
$deadline = (Get-Date).AddMinutes(10)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 10
    if ((docker inspect $name -f '{{.State.Status}}') -ne "running") {
        Write-Error "容器已退出；查看日志： docker logs $name"
        exit 1
    }
    try {
        $r = Invoke-RestMethod -Uri "http://localhost:8000/v1/models" -TimeoutSec 5
        Write-Host ("READY: " + (($r.data | ForEach-Object id) -join ", "))
        exit 0
    } catch { }
}
Write-Warning "10 分钟内未就绪；查看日志： docker logs $name"
