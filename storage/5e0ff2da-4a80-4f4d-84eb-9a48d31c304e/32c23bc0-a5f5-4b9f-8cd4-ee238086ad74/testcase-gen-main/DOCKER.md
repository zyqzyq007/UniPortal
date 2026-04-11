# Docker 构建与运行说明

本文档说明当前项目的 Docker 构建与运行方式。

## 1. 构建镜像

在项目根目录执行以下命令构建镜像：

```bash
docker build -t testcase-gen:latest .
```

## 2. 运行容器

使用以下命令启动容器（将容器内的 8000 端口映射到宿主机的 8001 端口）：

```bash
docker run -d -p 8001:8000 --name testcase-gen-test testcase-gen:latest
```

```bash
docker rm -f testcase-gen-test # 移除原来的
```


### 数据持久化运行（推荐）

为了防止容器重启后丢失上传的项目和生成的测试用例，建议挂载 `workspaces` 目录：

```bash
docker run -d \
  -p 8007:8000 \
  --name testcase-gen-test \
  -v $(pwd)/workspaces:/app/workspaces \
  testcase-gen:latest
```

> **参数说明**：
> * `-p 8001:8000`: 将宿主机的 **8001** 端口映射到容器的 **8000** 端口。
> * `--name testcase-gen-test`: 指定容器名称。
> * `-v ...`: 挂载本地目录以持久化数据。

## 3. 访问服务

启动成功后，可以通过以下地址访问：

- **前端页面**：[http://localhost:8007/index.html](http://localhost:8007/index.html)
- **后端 API 健康检查**：[http://localhost:8007/api/health](http://localhost:8007/api/health)
- **API 文档 (Swagger)**：[http://localhost:8007/docs](http://localhost:8007/docs)

## 4. Docker Compose 启动（与 UniPortal 集成）

当本工具作为 UniPortal 的子工具运行时，使用 Docker Compose 以共享卷的方式接入。

> **前提**：UniPortal 必须先启动（会创建 `uniportal_storage` 共享命名卷），本工具再启动。

### 首次启动 / 重新构建

```bash
docker-compose up --build -d
```

### 日常启动（镜像已构建）

```bash
docker-compose up -d
```

### 停止并移除容器

```bash
docker-compose down
```

### 强制重建并重启（代码有改动时）

```bash
docker-compose down && docker-compose up --build -d
```

> **端口**：服务监听宿主机 **8000** 端口，访问地址同第 3 节（将端口改为 `8000`）。
>
> **共享卷说明**：
> - `uniportal_storage`（只读）：挂载到容器 `/data/uniportal`，工具从此路径读取 UniPortal 上传的源码。通过环境变量 `UNIPORTAL_STORAGE_PATH=/data/uniportal` 告知应用。
> - `tool_tasks`（读写）：挂载到容器 `/app/workspaces/_tasks`，存放每次编译/运行的任务沙盒，仅本工具使用。

---

## 5. 常用管理命令

* **查看日志**：
  ```bash
  docker logs -f testcase-gen-test
  ```

* **停止并删除容器**：
  ```bash
  docker stop testcase-gen-test && docker rm testcase-gen-test
  ```

* **进入容器终端**：
  ```bash
  docker exec -it testcase-gen-test bash
  ```

## 6. 环境验证

容器内部已集成了完整的 C 语言编译和调试环境（GCC, GDB, Valgrind, Joern 等）。如果需要验证环境是否正常，可以运行：

```bash
# 验证 GCC, Math 库 (-lm) 和 Zlib (-lz)
docker exec testcase-gen-test sh -c 'echo "#include <zlib.h>\nint main(){return 0;}" > /tmp/check.c && gcc /tmp/check.c -o /tmp/check -lz && echo "Environment OK"'
```
