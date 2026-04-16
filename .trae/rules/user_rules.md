ANSWER IN CHINESE!
.trae/reference/ref.txt（如果没有请新建）里面是需要参考的github地址或接口文档；
通过notebooklm-skill找类似参考给出可行性分析，补充到该文件.trae/reference/ref.txt；
global参数前置到py文件最上边，并在注释中给出具体使用位置（精确到行）；
完成所有任务清单，完成之前不要退出;
TDD模式，每个任务开始前先删除之前的测试脚本，开始写当前测试脚本，必须有超时机制，脚本必须通过测试才算完成任务;
将user_rules.md文件中的所有规则都保存在：.trae/rules/user_rules.md中;
如果有git仓库，先暂存本地修改，然后git pull，拉取main分支，并且本地分支也使用main;
Create python venv evironment(use command: uv), and install python packages in requirements.txt;
每次对话后都要检查python脚本的import不缺失，requirements.txt里的模块不缺失，requirements.txt里面不要写版本号，requirements_{python version}.txt里面写版本号;
每次对话后都要git push to origin:main，commit内容就是我说的那句话。user.email="939342547@qq.com", user.name="qq939", remote=https://github.com/qq939/{projectName}, branch=main, when push to this remote, maybe you need to create remote repository(use: gh repo create {projectName} --public);
如果git推送到远端失败，rebase并且push --force-with-lease