#!/bin/bash

echo "正在清理项目，准备保存镜像..."

# 1. 清理临时工作区
echo "清理 workspaces..."
rm -rf workspaces/*
rm -rf workspace # 旧的 joern 垃圾目录

# 2. 清理 Python 缓存
echo "清理 __pycache__..."
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -type f -name "*.pyc" -delete

# 3. 清理前端缓存 (保留 node_modules 以便快速启动)
echo "清理前端构建缓存..."
rm -rf Frontend/dist
# 如果想进一步减小体积，可以把 node_modules 也删了，让用户启动时再装，但保留会启动更快
# rm -rf Frontend/node_modules 

# 4. 清理日志
echo "清理日志文件..."
rm -f *.log
rm -f nohup.out

# 5. 清理 Joern 临时文件
echo "清理 Joern 临时文件..."
rm -rf /tmp/joern*
rm -rf /tmp/dot*

echo "========================================================"
echo "清理完成！您的项目体积已优化。"
echo "现在您可以去 AutoDL 控制台执行 '创建镜像' 操作了。"
echo "========================================================"
echo "下次启动镜像后，只需运行: ./start.sh 即可启动服务。"
