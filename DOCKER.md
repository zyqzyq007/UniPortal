# UniPortal Docker 部署指南

本指南详细说明了如何使用 Docker 容器化部署 UniPortal 应用（前端 Vue + 后端 Express）。本项目采用单容器全栈部署方案，无需分别启动前后端服务。

## 📋 前置要求

- 确保本机已安装 [Docker](https://docs.docker.com/get-docker/) 和 Docker Compose。

## 🚀 快速开始 (一键运行)

### 方式一：使用 Docker Compose (推荐)

这是最简单的方式，适合所有场景。它会自动停止并删除旧容器，然后重建并启动新容器。

在项目根目录下执行：

```bash
docker-compose down && docker-compose up --build -d
```

### 方式二：使用原生 Docker 命令

如果你使用原生命令，需要先删除同名容器以避免冲突。可以使用以下组合命令（一键清理并启动）：

```bash
docker rm -f uni-portal || true && \
docker build -t uni-portal . && \
docker run -d -p 8080:8080 --name uni-portal uni-portal
```

启动完成后，请在浏览器访问：👉 **http://localhost:8080**

---

## 🛠 详细操作说明

### 1. 构建镜像

构建过程包含三个阶段：前端构建、后端构建、最终镜像打包。

```bash
docker build -t uni-portal .
```

### 2. 运行容器

#### 基础运行 (测试用)
数据存储在容器内部，重启容器后数据可能丢失。

```bash
docker run -p 8080:8080 uni-portal
```

#### 持久化运行 (生产推荐)
将数据库文件和上传文件挂载到宿主机，确保数据安全。

1. **准备文件**：在宿主机创建一个空的数据库文件（如果不存在）。
   ```bash
   touch prod.db
   mkdir -p storage
   ```

2. **启动容器**：
   ```bash
   docker run -d \
     -p 8080:8080 \
     -v $(pwd)/prod.db:/app/server/prod.db \
     -v $(pwd)/storage:/app/server/storage \
     --name uni-portal \
     uni-portal
   ```

### 3. 查看日志

如果遇到问题，可以通过查看容器日志来排查：

```bash
# 实时查看日志
docker logs -f uni-portal
```

---

## ⚙️ 配置项

你可以通过环境变量来配置应用行为：

| 环境变量 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `PORT` | `8080` | 服务监听端口 |
| `JWT_SECRET` | `default_secret_please_change` | JWT 签名密钥 (生产环境务必修改) |
| `DATABASE_URL` | `file:./prod.db` | 数据库连接字符串 |
| `SERVE_STATIC` | `true` | 是否由后端托管前端静态文件 |

**示例：修改 JWT 密钥启动**

```bash
docker run -p 8080:8080 -e JWT_SECRET="my_secure_secret_key" uni-portal
```

---

## 🏗 架构说明

本项目使用了 Docker **多阶段构建 (Multi-stage Build)** 技术，生成的镜像体积小且安全：

1.  **frontend-builder 阶段**：
    *   基于 `node:20-alpine`
    *   运行 `npm run build` 编译 Vue 前端代码，生成静态文件 (`dist`)。
2.  **backend-builder 阶段**：
    *   基于 `node:20-alpine`
    *   运行 `npx prisma generate` 生成数据库客户端。
    *   运行 `npm run build` 编译 TypeScript 后端代码。
3.  **runner 阶段 (最终镜像)**：
    *   仅包含运行时必要的 `node_modules` (生产依赖) 和构建产物。
    *   自动安装 `openssl` (Prisma 依赖)。
    *   启动时自动执行 `prisma db push` 同步数据库结构。
    *   后端 Express 服务同时负责 API 响应和前端静态资源托管。

## ❓ 常见问题排查

**Q: 注册时提示 "Internal Server Error"？**
A: 请检查日志 (`docker logs uni-portal`)。通常是因为数据库未正确初始化。我们的 Dockerfile 已包含自动初始化命令，但如果挂载了外部的损坏数据库文件，可能会导致此问题。

**Q: 登录后提示 "401 Unauthorized"？**
A: 这是因为 Token 未正确传递。请确保前端代码中的请求拦截器已正确配置 Token header。

**Q: 如何重新初始化数据库？**
A: 停止并删除容器，删除宿主机的 `prod.db` 文件，然后重新运行启动命令。容器启动时会自动创建一个新的数据库。
