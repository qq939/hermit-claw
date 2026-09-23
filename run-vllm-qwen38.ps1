# run-vllm-qwen38.ps1
# 拉起本地 Qwen3.8-27B 推理服务，供 hermit 的 localqwen profile 使用。
#
# 2026-09 架构更换：原为 vLLM（W4A16），现改为 llama.cpp GGUF，容器名 llama-qwen38。
#   vLLM 版权重 18.21 GiB 塞不进 16GB 显存，必须 --cpu-offload-gb 8，实测仅 2-3 tok/s；
#   GGUF 版 12.41 GiB 可全部进显存、无 offload，实测约 41 tok/s。
#   端口与模型名两者一致（:8000 / qwen3.8-27b），所以 hermit 侧配置无需改动。
#
# 真值源（模型与 compose 同目录）：
#     C:\Users\qq939\Downloads\qwen38\docker-compose.yml
# 本脚本只是"切到该目录 → docker compose up -d → 等 /v1/models 就绪"的薄封装。
# 参数为什么是这些，见那个 compose 文件里的注释（-ngl 99 / -c 8192 / -fa on / --jinja / -np 1 / --cache-ram 0）。
#
# 注意：compose 内 llama-qwen38 与 vLLM 版 qwen38 互斥（都要独占 GPU 与 :8000），
#       必须显式带服务名，否则走默认 profile 会拉起 vLLM 版。
#
# 用法： .\run-vllm-qwen38.ps1
# 就绪： curl http://localhost:8000/v1/models  → qwen3.8-27b

$ErrorActionPreference = "Stop"

$composeDir = "C:\Users\qq939\Downloads\qwen38"
$composeFile = Join-Path $composeDir "docker-compose.yml"
$name = "llama-qwen38"

if (-not (Test-Path $composeFile)) {
    Write-Error "找不到 compose 文件：$composeFile"
    exit 1
}

Write-Host "compose: $composeFile"
Push-Location $composeDir
try {
    docker compose up -d llama-qwen38
    if ($LASTEXITCODE -ne 0) {
        Write-Error "docker compose up 失败"
        exit 1
    }
} finally {
    Pop-Location
}

Write-Host "容器已启动，首次加载 GGUF 权重约 1-2 分钟..."
$deadline = (Get-Date).AddMinutes(10)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
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
