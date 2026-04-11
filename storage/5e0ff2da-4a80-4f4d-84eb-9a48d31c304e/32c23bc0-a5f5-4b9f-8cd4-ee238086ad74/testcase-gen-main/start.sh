#!/bin/bash

# =================================================================
# C Unit Test Generator - 一键启动脚本
# =================================================================

# 颜色定义
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}====================================================${NC}"
echo -e "${BLUE}       C Unit Test Generator 启动中...             ${NC}"
echo -e "${BLUE}====================================================${NC}"

# 获取项目根目录
PROJECT_ROOT=$(pwd)

# 1. 启动后端
echo -e "${YELLOW}[1/2] 正在启动后端服务 (FastAPI)...${NC}"

# check for existing backend process
# 使用 Python 检测占用 8000 端口的进程 (更可靠，因为 lsof/netstat 可能缺失)
EXISTING_PID=$(python3 -c "
import glob, os, sys
try:
    with open('/proc/net/tcp', 'r') as f:
        lines = f.readlines()
    inode = None
    for line in lines[1:]:
        parts = line.split()
        if ':1F40' in parts[1] and parts[3] == '0A': # 1F40=8000, 0A=LISTEN
            inode = parts[9]
            break
    if inode:
        for proc in glob.glob('/proc/[0-9]*'):
            try:
                fd_dir = os.path.join(proc, 'fd')
                if os.path.exists(fd_dir):
                    for fd in os.listdir(fd_dir):
                        try:
                            if os.readlink(os.path.join(fd_dir, fd)) == f'socket:[{inode}]':
                                print(os.path.basename(proc))
                                sys.exit(0)
                        except: pass
            except: pass
except: pass
")

if [ -n "$EXISTING_PID" ]; then
    echo -e "${YELLOW}检测到端口 8000 被占用 (PID: $EXISTING_PID)，正在强制停止...${NC}"
    kill -9 $EXISTING_PID
    sleep 1
fi

if [ -f "requirements.txt" ]; then
    # 检查是否在虚拟环境中，如果不在则提示
    if [ -z "$VIRTUAL_ENV" ]; then
        echo -e "${YELLOW}提示: 未检测到 Python 虚拟环境，将使用系统 Python 运行。${NC}"
    fi
    
    # 后台启动 uvicorn
    uvicorn app.main:app --host 0.0.0.0 --port 8000 &
    BACKEND_PID=$!
    
    # 等待几秒检查后端是否启动成功
    sleep 2
    if ps -p $BACKEND_PID > /dev/null; then
        echo -e "${GREEN}✔ 后端服务已启动 (PID: $BACKEND_PID)，端口: 8000${NC}"
    else
        echo -e "${RED}✘ 后端服务启动失败${NC}"
        exit 1
    fi
else
    echo -e "${RED}✘ 找不到 requirements.txt，请确保在项目根目录运行此脚本。${NC}"
    exit 1
fi

# 2. 启动前端
echo -e "${YELLOW}[2/2] 正在启动前端服务 (Vue/Vite)...${NC}"
if [ -d "Frontend" ]; then
    cd Frontend

    # 检查 5173 端口是否被占用并清理
    FRONTEND_PID=$(python3 -c "
import glob, os, sys
try:
    with open('/proc/net/tcp', 'r') as f:
        lines = f.readlines()
    inode = None
    for line in lines[1:]:
        parts = line.split()
        if ':1435' in parts[1] and parts[3] == '0A': # 1435=5173, 0A=LISTEN
            inode = parts[9]
            break
    if inode:
        for proc in glob.glob('/proc/[0-9]*'):
            try:
                fd_dir = os.path.join(proc, 'fd')
                if os.path.exists(fd_dir):
                    for fd in os.listdir(fd_dir):
                        try:
                            if os.readlink(os.path.join(fd_dir, fd)) == f'socket:[{inode}]':
                                print(os.path.basename(proc))
                                sys.exit(0)
                        except: pass
            except: pass
except: pass
")

    if [ -n "$FRONTEND_PID" ]; then
        echo -e "${YELLOW}检测到端口 5173 被占用 (PID: $FRONTEND_PID)，正在强制停止...${NC}"
        kill -9 $FRONTEND_PID
        sleep 1
    fi
    
    # 检查 node_modules 是否存在
    if [ ! -d "node_modules" ]; then
        echo -e "${YELLOW}检测到未安装前端依赖，正在执行 npm install...${NC}"
        npm install
    fi
    
    # 启动前端服务
    # 使用 nohup 或直接运行（因为是最后一个进程）
    echo -e "${GREEN}✔ 前端服务启动中...${NC}"
    echo -e "${BLUE}访问地址: http://localhost:5173${NC}"
    echo -e "${YELLOW}按 Ctrl+C 可同时停止前后端服务${NC}"
    
    # 捕获 Ctrl+C 信号以关闭后端
    trap "echo -e '\n${YELLOW}正在关闭服务...${NC}'; kill $BACKEND_PID; exit" SIGINT SIGTERM
    
    npm run dev || echo -e "${RED}前端服务异常退出，退出码: $?${NC}"
else
    echo -e "${RED}✘ 找不到 Frontend 目录${NC}"
    kill $BACKEND_PID
    exit 1
fi
