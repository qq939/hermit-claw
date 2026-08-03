# 十一、Git 管理规范（重要！）

每个项目必须初始化 Git 仓库，并在每次对话后执行提交：

1. 初始化仓库（如尚未初始化）
   git init
   git add .
   git commit -m "Initial commit"

2. 每次对话后必须提交
   完成任何任务后，必须执行：
     git add .
     git commit -m "描述本次变更"

3. 必须维护的文件
   - .gitignore：确保不提交 log/、node_modules/、.DS_Store、__pycache__/ 等
   - logs/commit.txt：记录每次 commit 的 ID 和标题，格式：
       {commit_id} {commit_title}
     每行一条，持续追加

4. logs/commit.txt 格式示例：
   a1b2c3d4 添加用户认证功能
   e5f6g7h8 修复登录页面样式问题
   i9j0k1l2 更新README文档

5. .gitignore 建议内容：
   logs/
   node_modules/
   .DS_Store
   __pycache__/
   *.log
   .env
   uploads/
   dist/
   build/
