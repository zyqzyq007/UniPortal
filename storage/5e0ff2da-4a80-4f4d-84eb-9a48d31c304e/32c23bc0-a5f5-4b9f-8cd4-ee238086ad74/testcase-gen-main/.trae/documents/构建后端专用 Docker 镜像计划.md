构建后端专用 Docker 镜像的最佳实践是创建一个独立的 `Dockerfile.backend`，剥离前端依赖（Node.js/npm），仅保留后端运行所需的 Python 环境和 Joern 工具链。

我将为您执行以下操作：

1. **创建** **`Dockerfile.backend`** **文件**：

   * **基础镜像**：保持 `python:3.10-slim-bookworm`。

   * **系统依赖**：仅安装后端必需的 `openjdk-17-jdk` (Joern 需要)、`gcc`、`graphviz` 等，移除 Node.js 和前端构建工具。

   * **应用依赖**：安装 Joern 工具链和 `requirements.txt` 中的 Python 库。

   * **文件复制**：仅复制 `app/` (代码)、`input/` (示例输入)、`resources/` (资源文件) 和 `requirements.txt`，排除前端代码以减小镜像体积。

   * **启动命令**：直接使用 `uvicorn` 启动后端服务。

2. **创建** **`.dockerignore`** **文件**（如果不存在）：

   * 确保构建上下文不包含 `venv`、`__pycache__`、`.git` 等无关文件，加快构建速度。

### 生成的 Dockerfile.backend 预览：

```dockerfile
# 仅后端构建配置
FROM python:3.10-slim-bookworm

# 环境变量设置 (保持与原版一致)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    JOERN_HOME=/opt/joern/joern-cli \
    PATH="/opt/joern/joern-cli:${PATH}"

# 安装后端运行时依赖 (移除 Node.js/npm)
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-17-jdk \
    gcc \
    graphviz \
    curl \
    unzip \
    wget \
    git \
    && rm -rf /var/lib/apt/lists/*

# 安装 Joern (保持与原版一致)
WORKDIR /opt/joern
RUN wget -q https://github.com/joernio/joern/releases/latest/download/joern-cli.zip \
    && unzip -q joern-cli.zip \
    && rm joern-cli.zip \
    && chmod +x joern-cli/joern joern-cli/joern-parse

# 设置工作目录
WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码及资源 (显式复制，避免包含前端文件)
COPY app ./app
COPY input ./input
COPY resources ./resources

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

