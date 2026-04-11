#!/bin/bash

# 检查是否安装了 git
if ! command -v git &> /dev/null; then
    echo "错误: 未找到 git 命令，请先安装 git"
    exit 1
fi

# 初始化仓库（如果尚未初始化）
if [ ! -d ".git" ]; then
    echo "正在初始化 Git 仓库..."
    git init
    # 默认分支名设为 main
    git branch -m main
else
    echo "Git 仓库已存在"
fi

# 确保 .gitignore 包含需要忽略的文件
if ! grep -q "joern-cli.zip" .gitignore; then
    echo "joern-cli.zip" >> .gitignore
    echo "已将 joern-cli.zip 添加到 .gitignore"
fi

# 添加所有文件（.gitignore 中的文件会被自动忽略）
echo "正在添加文件..."
git add .

# 提交
echo "正在提交更改..."
git commit -m "Initial commit: Upload project files (excluding large binaries)"

echo "=========================================="
echo "本地提交完成！"
echo "接下来请执行以下命令推送到 GitHub："
echo "1. git remote add origin <您的GitHub仓库地址>"
echo "2. git push -u origin main"
echo "=========================================="
