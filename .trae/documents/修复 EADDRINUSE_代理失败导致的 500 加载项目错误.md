## 一、错误分析（对应你给的三段日志）

### 1) 浏览器控制台：`Failed to load project {code: 500, message: Error, data: }`
- 触发点在 [ProjectHome.vue](file:///Users/bytedance/kairos/tasks/UniPortal/src/pages/projects/ProjectHome.vue#L262-L297) 的 `fetchProjectData()`：并发请求 `getProject()` 和 `getProjectStructure()`，任一失败进入 `catch`。
- 这里的 `{code,message,data}` 并不是后端原样返回，而是前端 Axios 封装在 [request.ts](file:///Users/bytedance/kairos/tasks/UniPortal/src/utils/request.ts#L26-L55) 里统一包装的：
  - `code` = HTTP status
  - `message` = `response.data.message || 'Error'`
  - `data` = `response.data`
- 你看到 `message: Error` 且 `data` 为空，通常意味着：请求确实收到了一个 **HTTP 500**，但响应体不是 JSON（甚至为空）。

### 2) 后端输出（Terminal#529-552）：`EADDRINUSE :::8080`
- 这是 **运行时错误**：后端启动时 `app.listen(8080)` 失败，因为 8080 端口已被占用。
- 结果是 nodemon 进程崩溃并停止监听（`app crashed - waiting for file changes`），导致后端服务实际不可用。
- 对应代码位置：[index.ts](file:///Users/bytedance/kairos/tasks/UniPortal/server/src/index.ts#L6-L10) 当前没有 `server.on('error')` 处理，因此直接抛错退出。

### 3) 前端输出（Terminal#188-201）：Vite `http proxy error ... ECONNREFUSED`
- 这是 **网络/代理层错误**：Vite 将 `/api/*` 代理到 `http://localhost:8080`，但目标端口拒绝连接（因为后端已崩）。
- Vite 在这种情况下会向浏览器返回一个 **HTTP 500（通常无 JSON body）**，于是 Axios 拦截器把它包装成 `{ code: 500, message: 'Error', data: '' }`。

结论：这次 “加载项目 500” 不是业务查询报错，而是 **后端端口占用导致服务启动失败 → Vite 代理连接被拒绝 → 前端收到 500 空响应**。

---

## 二、修复目标
1. 后端遇到端口占用时提供明确指引（而不是静默崩溃）。
2. 前端遇到代理/后端不可用时展示可理解的错误（而不是 `Error`）。
3. 保证修改后通过单元/集成测试，不引入新问题。

---

## 三、修复步骤（将会落地的代码改动）

### Step 1：解决 8080 端口占用（运行时层面）
- 在本机定位占用 8080 的进程并停止（例如 `lsof -i :8080` / `kill`），然后再启动后端。
- 同时，为了避免以后再次踩坑：
  - 改造 [index.ts](file:///Users/bytedance/kairos/tasks/UniPortal/server/src/index.ts) 为：
    - 显式 `const port = Number(process.env.PORT || 8080)`
    - `const server = app.listen(port, ...)`
    - `server.on('error', (err) => { if (err.code === 'EADDRINUSE') 打印“端口被占用”+建议命令并退出 })`

### Step 2：前端错误归因与友好提示（代理/网络层面）
- 在 [request.ts](file:///Users/bytedance/kairos/tasks/UniPortal/src/utils/request.ts) 的响应拦截器中补强：
  - 当 `status === 500` 且 `data` 为空/非对象时，将其识别为“代理失败/后端不可用”的高概率场景。
  - 将错误 message 变为：
    - `后端服务不可用（可能端口被占用或未启动），请确认 API 服务运行在 8080`
  - 可选：把 code 改为更语义化的 503（前端内部），避免跟真实业务 500 混淆。

### Step 3：ProjectHome 页面提示优化（UI 层面）
- 在 [ProjectHome.vue](file:///Users/bytedance/kairos/tasks/UniPortal/src/pages/projects/ProjectHome.vue) 的 `catch` 分支中：
  - 针对 `code === 503`（或识别后的代理失败）显示“后端不可用”文案。
  - 保留“重试/返回列表”操作。

---

## 四、验证与测试

### 1) 后端测试
- 运行 `server` 现有 Jest 集成测试（已覆盖项目 CRUD、结构、删除）。

### 2) 前端构建验证
- 运行 `npm run build`（包含 `vue-tsc`）确保 TS/模板无错误。

### 3) 联调验证
- 启动后端（确保 8080 可用）+ 启动前端，进入项目详情页：
  - 后端正常：项目可加载
  - 后端停掉或端口冲突：页面明确提示“后端不可用”，不再显示模糊 `Error`

---

## 五、交付物（改动文件清单）
- 后端：
  - [index.ts](file:///Users/bytedance/kairos/tasks/UniPortal/server/src/index.ts)
- 前端：
  - [request.ts](file:///Users/bytedance/kairos/tasks/UniPortal/src/utils/request.ts)
  - [ProjectHome.vue](file:///Users/bytedance/kairos/tasks/UniPortal/src/pages/projects/ProjectHome.vue)

批准后我将按以上步骤落地代码修改，并跑完整测试验证。