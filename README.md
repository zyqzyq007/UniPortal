# UniPortal — 软件测试一体化平台

UniPortal 是一个面向软件测试全流程的一体化管理平台，提供测试项目管理、软件条目上传与浏览、以及多种 AI 辅助测试子工具的统一入口。平台采用前后端分离架构，支持 Docker 单容器一键部署。

---

## ✨ 主要功能

| 模块 | 说明 |
|---|---|
| **用户认证** | 注册 / 登录，基于 JWT + Cookie 的鉴权机制 |
| **测试项目管理** | 创建、搜索、排序、删除测试项目，支持项目概览看板 |
| **软件条目管理** | 上传 zip 压缩包或整个文件夹，自动解压并以 UUID 命名存储，支持在线预览文件树与源码 |
| **工具中心** | 统一入口跳转至各 AI 子工具（需求验证、需求追溯、单元测试、系统测试、缺陷修复等） |
| **任务管理** | 查看各工具执行的任务列表与任务详情 |
| **结果查看** | 展示任务执行结果 |
| **用户中心** | 个人信息管理 |

### 集成的 AI 子工具

| 工具名称 | 功能描述 |
|---|---|
| 需求验证工具 | 上传文档，自动审查一致性与风险点 |
| 需求追溯工具 | 解析需求文本，输出结构化语义标签与澄清点 |
| 代码智能分析 | 对指定仓库或分支进行静态扫描与质量分析 |
| 智能单元测试 | 自动生成单元测试或补全已有测试用例 |
| 智能配置项/系统测试 | 基于配置项进行系统级测试与回归验证 |
| 代码缺陷智能修复 | 定位缺陷并生成修复建议或补丁 |

---

## 🏗 技术栈

### 前端
- **框架**：Vue 3 + TypeScript + Vite
- **路由**：Vue Router 4
- **图表**：ECharts / vue-echarts
- **代码编辑器**：Monaco Editor + vue-codemirror
- **HTTP 客户端**：Axios
- **测试**：Vitest + @vue/test-utils

### 后端
- **运行时**：Node.js 20
- **框架**：Express
- **ORM**：Prisma（开发环境：SQLite，生产环境可切换为 PostgreSQL）
- **认证**：JWT + bcryptjs
- **文件上传**：Multer
- **压缩处理**：adm-zip
- **API 文档**：Swagger（访问 `/api-docs`）
- **测试**：Jest + Supertest

### 部署
- Docker 多阶段构建（前端构建 → 后端构建 → 生产镜像）
- Docker Compose 编排
- Nginx 反向代理

---

## 📁 项目结构

```
UniPortal/
├── src/                        # 前端源码（Vue 3）
│   ├── pages/                  # 页面组件
│   │   ├── auth/               # 登录页
│   │   ├── projects/           # 项目列表、项目详情、软件条目、源码浏览
│   │   ├── tools/              # 工具中心、工具 iframe 容器
│   │   ├── tasks/              # 任务列表与详情
│   │   └── result/             # 结果展示
│   ├── components/             # 通用组件（文件树、代码编辑器、图表等）
│   ├── api/                    # Axios 请求封装
│   ├── router/                 # 路由配置
│   ├── store/                  # 状态管理
│   ├── mock/                   # 子工具配置与静态数据
│   └── utils/                  # 工具函数
├── server/                     # 后端源码（Express）
│   ├── src/
│   │   ├── controllers/        # 业务控制器（auth、project）
│   │   ├── routes/             # 路由定义
│   │   ├── middleware/         # 认证中间件
│   │   ├── services/           # 业务服务层
│   │   └── prisma.ts           # Prisma 客户端实例
│   ├── prisma/
│   │   └── schema.prisma       # 数据库模型定义
│   ├── storage/                # 软件文件存储根目录（挂载为 Docker 命名卷）
│   └── tests/                  # 后端测试
├── Dockerfile                  # 多阶段构建配置
├── docker-compose.yml          # 容器编排配置
└── nginx.conf                  # Nginx 配置
```

---

## 🚀 快速开始

### 方式一：Docker Compose（推荐）

```bash
# 1. 克隆项目
git clone https://github.com/zyqzyq007/UniPortal.git
cd UniPortal

# 2. 启动（首次构建约需 2~3 分钟）
docker compose down -v && docker compose up --build -d

# 3. 查看启动日志
docker logs -f uni-portal
```

启动成功后访问：👉 **http://211.71.15.55:8080**

> ⚠️ 本机使用 Docker Compose V2，命令为 `docker compose`（空格），而非 `docker-compose`（连字符）。

### 方式二：本地开发

**前提**：Node.js 20+

```bash
# 安装前端依赖
npm install

# 安装后端依赖
cd server && npm install

# 初始化数据库
cd server && npx prisma db push

# 启动后端（新终端）
cd server && npm run dev

# 启动前端（新终端）
npm run dev
```

---

## ⚙️ 环境变量

在 `server/` 目录下创建 `.env` 文件：

```env
PORT=8080
DATABASE_URL=file:./dev.db
JWT_SECRET=your_secret_key_here
SERVE_STATIC=true
```

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PORT` | `8080` | 服务监听端口 |
| `DATABASE_URL` | `file:./prod.db` | 数据库连接字符串 |
| `JWT_SECRET` | `default_secret_please_change` | JWT 签名密钥（生产环境务必修改） |
| `SERVE_STATIC` | `true` | 是否由后端托管前端静态文件 |

---

## 🔗 共享卷（子工具数据共享）

UniPortal 上传的软件文件以 Docker 命名卷 `uniportal_storage` 形式存储，子工具容器可通过 `external: true` 直接挂载读取，**无需额外的文件传输**。

### 存储路径结构

```
uniportal_storage/
└── {portal_project_id}/        ← 测试项目 UUID（自动生成）
    └── {item_id}/              ← 软件条目 UUID（自动生成，非用户命名）
        └── {zip解压文件夹名}/   ← zip 包解压后的根目录
            ├── src/
            └── ...
```

> 路径中全部使用 UUID，不含任何用户输入的名称，避免中文、特殊字符引发路径问题。

### 子工具接入方式

在子工具的 `docker-compose.yml` 中声明：

```yaml
volumes:
  uniportal_storage:
    external: true    # 引用 UniPortal 已创建的命名卷

services:
  your-tool:
    volumes:
      - uniportal_storage:/data/uniportal:ro   # 只读挂载
    environment:
      - UNIPORTAL_STORAGE_PATH=/data/uniportal
```

> ⚠️ **启动顺序**：必须先启动 UniPortal，再启动子工具，否则 `external` 卷不存在会报错。

---

## 📡 API 文档

启动后访问：**http://211.71.15.55:8080/api-docs**（Swagger UI）

主要接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/auth/register` | 用户注册 |
| `POST` | `/api/auth/login` | 用户登录 |
| `GET` | `/api/auth/me` | 获取当前用户信息 |
| `GET` | `/api/projects` | 获取项目列表 |
| `POST` | `/api/projects` | 创建项目 |
| `GET` | `/api/projects/:id` | 获取项目详情 |
| `PUT` | `/api/projects/:id` | 更新项目 |
| `DELETE` | `/api/projects/:id` | 删除项目 |
| `POST` | `/api/projects/:id/items` | 上传软件条目（zip/文件夹） |
| `GET` | `/api/projects/:id/items` | 获取软件条目列表 |
| `DELETE` | `/api/projects/:id/items/:itemId` | 删除软件条目 |
| `GET` | `/api/projects/:id/items/:itemId/download` | 下载软件条目 |
| `GET` | `/api/projects/:id/items/:itemId/structure` | 浏览文件树 |
| `GET` | `/api/projects/:id/items/:itemId/file` | 读取文件内容 |
| `POST` | `/api/projects/:id/items/:itemId/operate` | 文件节点操作（新建/重命名/删除） |

---

## 🧪 运行测试

```bash
# 前端单元测试
npm run test

# 前端测试覆盖率
npm run test:coverage

# 后端测试
cd server && npm run test
```

---

## ❓ 常见问题

**Q: 启动后访问 8080 端口显示 502 Bad Gateway？**  
A: 通常是数据库挂载问题。执行以下命令重置：
```bash
docker compose down -v && docker compose up --build -d
```

**Q: 注册时提示 Internal Server Error？**  
A: 查看日志排查：`docker logs uni-portal`

**Q: 如何重置数据库？**  
A: 停止容器，删除命名卷后重新启动：
```bash
docker compose down -v
docker compose up -d
```
