# run-vllm-qwen38.ps1
# 拉起本地 vLLM（Qwen3.8-27B W4A16），供 hermit 的 localqwen profile 使用。
#
# 参数本身声明在 docker-compose.vllm.yml（唯一真值源），本脚本只是带就绪等待的薄封装。
# 这样就不会再出现"手敲 docker run、参数丢了重新踩坑"的问题，且 restart=unless-stopped
# 会在机器重启后自动拉起。
#
# 用法： .\run-vllm-qwen38.ps1
# 就绪： curl http://localhost:8000/v1/models  → qwen3.8-27b

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$compose = Join-Path $root "docker-compose.vllm.yml"
$name = "vllm-qwen38"

docker compose -f $compose up -d
if ($LASTEXITCODE -ne 0) {
    Write-Error "docker compose up 失败"
    exit 1
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
