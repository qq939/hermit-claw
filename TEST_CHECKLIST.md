# Hermit Claw Control 检查手册

## 每次修改后必须执行的检查步骤

### 1. 重建并部署
```bash
cd ~/.openclaw/workspace/skills/hermit-claw
docker compose build control-18080 && docker compose up -d --no-deps control-18080
```

### 2. 验证服务可用
```bash
curl -s http://localhost:18080/ | head -5
# 应返回 HTML 页面，不应有 500 错误
```

### 3. 检查日志
```bash
docker logs hermit-control-18080 2>&1 | tail -20
# 检查是否有错误
```

### 4. 测试创建容器
```bash
curl -s -X POST http://localhost:18080/api/agents \
  -H "Content-Type: application/json" \
  -d '{"type": "claude", "name": "test-manual"}' | jq .
# 应返回容器信息
```

### 5. 验证下拉框选项
```bash
curl -s http://localhost:18080/api/agent-types | jq .
# 应返回 claude 和 openclaw@2026.2.9
```

### 6. 浏览器验证
- 强制刷新: Cmd+Shift+R (Mac) 或 Ctrl+Shift+R (Windows)
- 检查页面是否有错误提示
- 检查按钮是否可点击
- 检查下拉框是否有选项

## 常见问题排查

### 500 Internal Server Error
```bash
docker logs hermit-control-18080
# 查看具体错误
```

### 按钮不可点击
1. 强制刷新浏览器
2. 检查浏览器控制台是否有JS错误
3. 清除浏览器缓存

### 下拉框为空
1. 检查HTML源码是否包含option
2. 检查/api/agent-types接口
3. 强制刷新

## 测试用例清单

- [ ] 页面加载正常
- [ ] 下拉框有claude选项
- [ ] 下拉框有openclaw@2026.2.9选项
- [ ] 一键创建按钮可点击
- [ ] 创建容器成功
- [ ] 容器正常运行
- [ ] 发送初始消息成功
- [ ] 日志有时间戳
- [ ] 日志和界面同步
