# run-vllm-qwen38.ps1
# 启动本地 vLLM（Qwen3.8-27B W4A16）供 hermit 的 localqwen profile 使用。
#
# 为什么需要这个脚本：
#   vllm-qwen38 是手工 docker run 出来的（无 compose、restart=no），一旦机器重启或容器被删，
#   这些"能跑通"的参数就会丢。踩过的坑（缺一个都跑不起来）：
#     1) --enable-auto-tool-choice + --tool-call-parser qwen3_xml
#        缺 → Claude Code 报 400 "auto tool choice requires --enable-auto-tool-choice"
#        解析器必须是 qwen3_xml（该模型输出 Qwen 的 <tool_call><function=..> XML 格式；
#        用 hermes 不会报错，但工具调用会以纯文本返回，Claude Code 无法执行工具）
#     2) --max-model-len：Claude Code 单次要 21333 output tokens + ~11.4k prompt，
#        4096 会直接 400（max_completion_tokens > max_model_len）；
#        49152 + fp8 KV 已实测可用（KV 容量 67k tokens，够 1.37x 并发）
#     3) --kv-cache-dtype fp8：fp16 只有 ~2.5GiB KV（17.7k tokens），装不下 32k+ 上下文
#     4) --cpu-offload-gb 8：27B W4A16 显存放不下（RTX 4080 16G），必须卸载部分权重到 CPU
#     5) ANTHROPIC_MODEL：容器里 claude CLI 的模型名必须给出（config/claude/settings.json[.p]
#        的 env 已带 ANTHROPIC_MODEL / ANTHROPIC_DEFAULT_*，重建容器后注入进程 env 即生效）
#
# 用法： .\run-vllm-qwen38.ps1
# 验证： curl http://localhost:8000/v1/models   → 应返回 qwen3.8-27b

$ErrorActionPreference = "Stop"

$name  = "vllm-qwen38"
$image = "vllm/vllm-openai:v0.29.0"
$model = "/models/models--bowmanslayer--Qwen3.8-27B-W4A16-vision-mtp/snapshots/3a57d8835438c865188e6ea039c11bbaa3353967"
$hostModels = "C:\Users\qq939\Downloads\qwen38"

# 已存在则先删（想保留旧容器请先自行 docker rename）
$existing = docker ps -a --format '{{.Names}}' | Where-Object { $_ -eq $name }
if ($existing) {
    Write-Host "removing existing container $name ..."
    docker rm -f $name | Out-Null
}

docker run -d --name $name `
    --gpus all --ipc host --shm-size 16g `
    -p 8000:8000 `
    -v "${hostModels}:/models" `
    -e HF_HUB_OFFLINE=1 -e VLLM_WSL2_ENABLE_PIN_MEMORY=1 `
    $image `
    --model $model `
    --served-model-name qwen3.8-27b `
    --max-model-len 49152 `
    --gpu-memory-utilization 0.90 `
    --cpu-offload-gb 8 `
    --enforce-eager `
    --trust-remote-code `
    --enable-auto-tool-choice `
    --tool-call-parser qwen3_xml `
    --kv-cache-dtype fp8

Write-Host "started. 首次加载约 2-4 分钟，等待 /v1/models 就绪："
$deadline = (Get-Date).AddMinutes(10)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 10
    if ((docker inspect $name -f '{{.State.Status}}') -ne "running") {
        Write-Error "container exited; check: docker logs $name"
        exit 1
    }
    try {
        $r = Invoke-RestMethod -Uri "http://localhost:8000/v1/models" -TimeoutSec 5
        Write-Host ("READY: " + (($r.data | ForEach-Object id) -join ", "))
        exit 0
    } catch { }
}
Write-Warning "not ready within 10 minutes; check: docker logs $name"
