## 诊断结论
### 1) EADDRINUSE: 8080
- 类型：运行时错误（端口占用）。
- 原因：8080 已被其他进程或容器占用，后端启动失败。
- 受影响位置：[index.ts](file:///Users/bytedance/kairos/tasks/UniPortal/server/src/index.ts#L1-L18)、Docker 端口映射 [docker-compose.yml](file:///Users/bytedance/kairos/tasks/UniPortal/docker-compose.yml#L1-L33)、反代配置 [nginx.conf](file:///Users/bytedance/kairos/tasks/UniPortal/nginx.conf#L1-L16)。

### 2) Prisma P2003 外键约束
- 类型：运行时错误（数据库约束）。
- 原因：JWT 里解析出的 userId 在数据库中不存在，导致 `project.create` 写入 `owner_id` 失败。
- 触发位置：[project.controller.ts](file:///Users/bytedance/kairos/tasks/UniPortal/server/src/controllers/project.controller.ts#L15-L87)
- 根因是鉴权中间件只做 JWT 验签，没有校验用户是否仍存在：[auth.middleware.ts](file:///Users/bytedance/kairos/tasks/UniPortal/server/src/middleware/auth.middleware.ts#L13-L27)。

---

## 修复方案（会落地的代码修改）
### A. 端口占用处理
1) 在启动层面输出更明确的指引（已有基本处理）
2) 开发环境允许使用替代端口（如 8081），并同步更新：
   - 前端 Vite 代理
   - docker-compose 映射
   - nginx 反代

### B. 外键错误修复
1) 在鉴权中间件增加“用户存在性校验”
   - JWT 验签后查询 `User` 是否存在
   - 不存在则返回 401，并清除 cookie
2) 在 `createProject` 中改用 `owner: { connect: { id } }`
   - 捕获 `P2025/P2003`，返回明确错误信息

---

## 实施步骤
1) 更新 [auth.middleware.ts](file:///Users/bytedance/kairos/tasks/UniPortal/server/src/middleware/auth.middleware.ts#L13-L27)：校验用户存在，不存在则 401 + 清 cookie。
2) 更新 [project.controller.ts](file:///Users/bytedance/kairos/tasks/UniPortal/server/src/controllers/project.controller.ts#L15-L87)：使用 connect 写入，并捕获 Prisma 已知错误给出友好返回。
3) 若需要修改端口：同步调整前端代理与 docker/nginx。
4) 运行后端 Jest 测试与前端 build 验证。

确认后我将按照以上步骤修改并提交验证。