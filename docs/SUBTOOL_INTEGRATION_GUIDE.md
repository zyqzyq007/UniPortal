# UniPortal 子工具数据对接约定（双数据源版）

> 适用对象：所有需要接入 UniPortal 的 AI 子工具开发者
> 目标：子工具同时支持 UniPortal 共享数据 + 自有上传功能

---

## 一、目标

子工具同时支持两个数据来源，**并存**，不互相替换：

- **A. UniPortal 共享卷**（只读）：用户在 UniPortal 上传的项目，所有子工具立即可见
- **B. 子工具自己的私有卷**（读写）：保留子工具原有的上传/管理功能，跟以前一样用

新接入工具**不需要砍掉原有上传接口**，只是多了一条"从共享卷读"的路径。

---

## 二、卷与目录约定

### 2.1 卷映射

| 卷 | 挂载点 | 权限 | 用途 |
|---|---|---|---|
| `uniportal_storage` | `/data/uniportal` | **只读** | 读 UniPortal 上传的项目 |
| `<tool>_local` | `/app/local_workspaces` | 读写 | 子工具自己上传 + 所有生成物 |
| `<tool>_tasks` | `/app/workspaces/_tasks` | 读写 | 运行沙盒（按需） |

### 2.2 共享卷目录结构（只读）

```
/data/uniportal/
└── {portal_project_id}/      ← UniPortal 测试项目 UUID
    └── {item_id}/            ← 软件条目 UUID  ← 用这个作为子工具的 project_id
        └── {解压后源码根目录}/
            ├── src/
            └── ...
```

### 2.3 私有卷目录结构（读写，原有结构不变）

```
/app/local_workspaces/
└── {your_own_project_id}/    ← 子工具自己生成的 ID，原来什么样还什么样
    └── ...
```

---

## 三、子工具 `docker-compose.yml` 模板

```yaml
version: "3.9"

services:
  your-tool:
    build: .
    image: your-tool
    container_name: your-tool
    ports:
      - "<host_port>:<container_port>"
    volumes:
      - uniportal_storage:/data/uniportal:ro     # 共享卷（只读）
      - tool_local:/app/local_workspaces         # 私有读写（自己的上传 + 生成物）
      - tool_tasks:/app/workspaces/_tasks        # 私有读写（沙盒，按需）
    environment:
      - UNIPORTAL_STORAGE_PATH=/data/uniportal   # 共享卷读取路径
      - LOCAL_WORKSPACES_DIR=/app/local_workspaces  # 私有写入路径
    restart: unless-stopped

volumes:
  uniportal_storage:
    external: true     # 必须！引用 UniPortal 已创建的卷
  tool_local:
    driver: local
  tool_tasks:
    driver: local
```

**三个红线**：

1. `external: true` 不能漏，否则会被当作新卷创建，跟 UniPortal 不通
2. `:ro` 一定要加，子工具不允许写共享卷
3. 私有卷不能挂到 `/data/uniportal` 下面

---

## 四、代码改造要点

**原有上传接口、原有项目管理逻辑全部保留**，只增加"从共享卷读"这一条路径。

### 4.1 写操作（上传 / 缓存 / 生成物）

完全不变，全部写到 `LOCAL_WORKSPACES_DIR`（即 `/app/local_workspaces`）。

```python
LOCAL_WORKSPACES_DIR = os.getenv("LOCAL_WORKSPACES_DIR", "workspaces")

# 用户在子工具里上传时
save_dir = LOCAL_WORKSPACES_DIR    # 跟以前一样
```

### 4.2 读操作（按 project_id 解析路径）

**先查私有，再查共享卷**——子工具自己的项目优先，找不到再去共享卷找：

```python
UNIPORTAL_PATH = os.getenv("UNIPORTAL_STORAGE_PATH")  # 可能为 None

def resolve_project_path(project_id: str) -> str:
    # 1. 私有卷（自己上传的）
    local = os.path.join(LOCAL_WORKSPACES_DIR, project_id)
    if os.path.exists(local):
        return local

    # 2. 共享卷（UniPortal 来的，按 item_id 在两层目录里查）
    if UNIPORTAL_PATH and os.path.exists(UNIPORTAL_PATH):
        for portal_proj in os.listdir(UNIPORTAL_PATH):
            candidate = os.path.join(UNIPORTAL_PATH, portal_proj, project_id)
            if os.path.isdir(candidate):
                return candidate

    raise NotFound(f"project_id {project_id} not found")
```

### 4.3 项目列表接口

接受可选参数 `portal_project_id`（由 UniPortal iframe 通过 URL query 传入），实现**按工程隔离**。每条记录带 `source` 字段方便前端区分来源：

- 传入 `portal_project_id` → 只列该工程下的 item + 全部私有上传
- 未传 `portal_project_id`（子工具独立访问）→ **只列私有上传**，不暴露任何 UniPortal 项目（避免跨工程数据泄露）

```python
def list_projects(portal_project_id: str = None):
    items = []

    # ① 共享卷：按工程隔离扫描
    if UNIPORTAL_PATH and os.path.exists(UNIPORTAL_PATH) and portal_project_id:
        proj_path = os.path.join(UNIPORTAL_PATH, portal_project_id)
        if os.path.isdir(proj_path):
            for item_id in os.listdir(proj_path):
                items.append({
                    "project_id": item_id,
                    "project_name": ...,
                    "file_count": ...,
                    "status": "available",
                    "source": "uniportal",
                })

    # ② 私有卷：永远列出（不受 portal_project_id 影响）
    for pid in os.listdir(LOCAL_WORKSPACES_DIR):
        items.append({
            "project_id": pid,
            "project_name": ...,
            "file_count": ...,
            "status": "available",
            "source": "local",
        })

    return items
```

对应的 FastAPI 路由：

```python
@router.get("/list", response_model=List[UploadResponse])
async def list_projects(portal_project_id: Optional[str] = None):
    projects = ProjectService.list_projects(portal_project_id=portal_project_id)
    return [UploadResponse(**p) for p in projects]
```

⚠️ 如果用 pydantic / FastAPI `response_model`，**响应模型也要声明 `source` 字段**，否则会被过滤掉（即使后端 dict 里有）。

### 4.4 删除接口

按来源限制：

```python
def delete_project(project_id):
    local = os.path.join(LOCAL_WORKSPACES_DIR, project_id)
    if os.path.exists(local):
        shutil.rmtree(local)
        return
    # 共享卷的项目不允许在子工具里删
    raise Forbidden("UniPortal 来源的项目请到 UniPortal 删除")
```

### 4.5 ID 命名

- 私有卷里用什么 ID 完全不变（比如 `proj_20260525_xxxx`）
- 共享卷里用 **`item_id`**（UUID）作为子工具的 project_id
- 两者天然不冲突，可以共存在一个列表里

---

## 五、UniPortal 跳转协议（工程隔离的关键）

UniPortal 跳转到子工具时，**在 URL 上附加 `portal_project_id` 查询参数**，告诉子工具"当前用户正在哪个工程下使用你"。子工具用此参数过滤可见项目，实现工程隔离。

> **核心契约只有一条**：子工具从 `URLSearchParams` 读 `portal_project_id`，按它过滤共享卷扫描范围。其余都是辅助实现。

### 5.1 端到端数据流

```
[1] 用户在 UniPortal 工程 X 的页面 → 工具中心 → 点"进入工具"
      ↓
[2] 新窗口打开 http://<子工具>:<port>/?portal_project_id=X
      ↓
[3] 子工具前端启动时从 URL query 读 portal_project_id，存 sessionStorage（应对 SPA 路由切换丢 query）
      ↓
[4] 前端调 GET /api/project/list?portal_project_id=X
      ↓
[5] 后端按 X 扫描共享卷 /data/uniportal/X/ 目录，只返回该工程下的 item
      ↓
[6] 列表里只看到工程 X 的项目 + 子工具自己的私有上传
```

**没有 `portal_project_id` 时（用户直接访问子工具 URL，不通过 UniPortal）的安全默认**：完全不展示任何 UniPortal 项目，只显示私有上传，防止跨工程数据泄露。

### 5.2 URL 协议

```
http://<sub_tool_host>:<port>/?portal_project_id=<UUID>
```

例：

```
http://211.71.15.55:8007/?portal_project_id=682c9812-38c2-4120-a0eb-d0b7288d603c
```

子工具如果有 SPA 路由，页面内跳转后 URL query 可能丢失，需要在前端**用 `sessionStorage` 兜底**（见 5.3）。

### 5.3 子工具前端实现（Pinia 示例）

```js
// 从 URL query 读 portal_project_id，存 sessionStorage 兜底
const _readPortalProjectId = () => {
  const fromUrl = new URLSearchParams(window.location.search).get('portal_project_id')
  if (fromUrl) {
    sessionStorage.setItem('portalProjectId', fromUrl)
    return fromUrl
  }
  return sessionStorage.getItem('portalProjectId') || null
}

export const useAppStore = defineStore('app', {
  state: () => ({
    portalProjectId: _readPortalProjectId(),
    // ...其他字段
  }),
})
```

调 list 接口时把它带上：

```js
const params = store.portalProjectId
  ? { portal_project_id: store.portalProjectId }
  : {}
const response = await axios.get('/api/project/list', { params })
```

### 5.4 子工具后端实现

参见 §4.3，list 函数接受可选 `portal_project_id`，FastAPI 路由暴露为 query 参数。**关键点**：未传时不返回任何 UniPortal 项目（安全默认）。

### 5.5 UniPortal 端实现（仅供 UniPortal 维护者参考，子工具开发者可跳过）

UniPortal 工具中心 `ToolsCenter.vue` 用 `<a target="_blank">` 跳转到子工具——这是**真实生效的入口**。生成 href 时拼接 `portal_project_id`：

```js
// src/pages/tools/ToolsCenter.vue
import { useRoute } from 'vue-router'

const route = useRoute()

const toolsList = computed(() => {
  const projectId = route.params.projectId as string | undefined
  return tools.map(tool => {
    let url = getToolUrl(tool.targetUrl)
    if (projectId) {
      const sep = url.includes('?') ? '&' : '?'
      url = `${url}${sep}portal_project_id=${encodeURIComponent(projectId)}`
    }
    return { ...tool, targetUrl: url }
  })
})
```

> 如果有些场景采用 iframe 嵌入（`ToolViewer.vue` 路由 `/projects/:id/tools/:toolKey`），用完全相同的拼接逻辑改它的 `targetUrl` computed。**两条入口都要改**，否则会有路径没传参导致工程隔离失效。

### 5.6 关于 item_id

打开**特定软件条目**的详情/操作接口时，URL 路径里仍然用 `item_id`（如 `/api/project/{item_id}/structure`）。`portal_project_id` 只用于**列表过滤**，不参与单个 item 的定位（item_id 全局唯一）。

### 5.7 不在工程隔离范围内的东西

明确以下**不**受 `portal_project_id` 影响（这是当前设计选择，不是 bug）：

- **私有上传**（`source="local"`）：子工具里用户自己上传的项目，无论哪个工程视角下都全部可见
- **单个 item 的访问接口**：知道 item_id 就能访问，跨工程不做校验。如需严格隔离，需要在 `get_project_path(item_id)` 里加 `portal_project_id` 反查校验，目前未实现
- **任务结果、生成产物**：与工程无关，按 item_id 关联

---

## 六、启动顺序

1. 先启 UniPortal（创建 `uniportal_storage` 卷）

   ```bash
   cd UniPortal && docker compose up -d
   ```

2. 再启子工具

   ```bash
   cd your-tool && docker compose up -d
   ```

顺序反了会报 `external volume "uniportal_storage" not found`。

---

## 七、验证清单

```bash
# 1. 共享卷被两个容器挂载到同一份数据
docker inspect uni-portal your-tool \
  --format '{{.Name}}: {{range .Mounts}}{{if eq .Name "uniportal_storage"}}{{.Source}} -> {{.Destination}} ({{.Mode}}){{end}}{{end}}'

# 2. 子工具能读到 UniPortal 项目
docker exec your-tool ls /data/uniportal
# 应列出 portal_project_id 列表

# 3. 子工具的私有上传仍然能写入
docker exec your-tool ls /app/local_workspaces

# 4. 集成模式开关已生效
docker exec your-tool env | grep UNIPORTAL_STORAGE_PATH
# 应输出 UNIPORTAL_STORAGE_PATH=/data/uniportal
```

四条全通过 = 双源接入成功，**原有功能 + UniPortal 互通**全在线。

---

## 八、常见坑

| 现象 | 原因 | 解决 |
|---|---|---|
| `external volume not found` | UniPortal 没先启 | 先起 UniPortal |
| 卷挂上了但读不到数据 | 卷名写错（如 `uniportal_uniportal_storage`） | 严格用 `uniportal_storage` |
| 子工具报"只读文件系统" | 把生成物/缓存写到了 `/data/uniportal` | 写入路径改为 `LOCAL_WORKSPACES_DIR` |
| 列表里看不到 UniPortal 项目 | list 接口只扫了私有卷 | 按 §4.3 合并两个来源 |
| 同一项目出现两次 | 私有目录里手动复制过共享卷的数据 | 去掉私有目录里的冗余 |
| 子工具能看 UniPortal 项目但无法生成结果 | 试图把缓存/CPG 写入 `/data/uniportal` | 生成物全部落到 `LOCAL_WORKSPACES_DIR` |
| **重启后 UniPortal 跟子工具又互不可见** | 用了 `docker-compose down -v`，老卷被释放，新卷被加上项目名前缀（如 `uniportal_uniportal_storage`）| 在 UniPortal compose `volumes:` 块给每个卷加 `name: uniportal_storage` 字段固化卷名；日常重启用 `docker compose up -d --build`，**不要用 down -v** |
| `docker-compose down -v` 把数据一起删了 | `-v` 会删除所有声明的命名卷的数据 | 重启请用 `docker compose up -d --build`；要重置 db 单独 `docker volume rm uniportal_db` |
| 后端 dict 里加了 `source` 字段但 API 返回没有 | FastAPI `response_model` / pydantic 模型未声明该字段，会被过滤 | 响应模型加 `source: Optional[str] = None` |
| 子工具看到了**其他工程**的项目 | list 接口没接收/没用 `portal_project_id` 过滤 | 按 §五 和 §4.3 改造：URL query 传 `portal_project_id`，后端按它扫描指定工程目录 |
| UniPortal 跳转后子工具只显示私有项目 / 列表空 | 跳转 URL 没拼 `portal_project_id`，子工具触发"无参数 → 只显示私有"的安全默认 | UniPortal 端**所有跳转入口都要拼参数**：`ToolsCenter.vue`（`<a target="_blank">` 新窗口跳转，**真实入口**）+ `ToolViewer.vue`（iframe 嵌入，可选）。漏改任何一个都会让该入口的工程隔离失效（见 §5.5） |
| 改了部分入口生效、部分入口失效 | UniPortal 端有多种跳转方式（按钮、iframe、菜单），只改了其中一处 | 全局搜 `tool.targetUrl` / `targetUrl: getToolUrl`，所有出现的地方都要补 `portal_project_id` 拼接 |
| 子工具页面刷新后丢了 portal_project_id | 子工具是 SPA，内部路由 `push` 后 URL query 丢失 | 前端启动时把 portal_project_id 存 `sessionStorage`（见 §5.3），别只靠 URL |

---

## 九、参考实现

`testcase-gen` + `UniPortal` 是当前已完成"双源接入 + 工程隔离"的参考组合。新工具接入时按下面两份清单对照改造即可。

### 9.1 子工具侧改造清单（以 testcase-gen 为参考）

| 文件 | 关键改动 |
|---|---|
| `testcase-gen/docker-compose.yml` | 挂 `uniportal_storage:/data/uniportal:ro` + 私有读写卷；设 `UNIPORTAL_STORAGE_PATH`、`LOCAL_WORKSPACES_DIR` 环境变量 |
| `testcase-gen/app/services/project_service.py` | `UNIPORTAL_MODE` 分支；`list_projects(portal_project_id=None)` 按工程过滤；`_build_item_index()`、`get_project_path()` 双源解析 |
| `testcase-gen/app/routers/project.py` | `/api/project/list` 路由暴露 `portal_project_id: Optional[str]` query 参数 |
| `testcase-gen/app/models/project.py` | `UploadResponse` 声明 `source: Optional[str] = None`，否则 FastAPI 会过滤该字段 |
| `testcase-gen/Frontend/src/store/index.js` | 从 URL query 读 `portalProjectId` + `sessionStorage` 兜底 |
| `testcase-gen/Frontend/src/views/UploadView.vue` | `fetchProjects` 调 list 接口时把 `portal_project_id` 作为 axios `params` 传给后端 |

### 9.2 UniPortal 侧改造清单（工程隔离落地）

| 文件 | 关键改动 |
|---|---|
| `UniPortal/docker-compose.yml` | `volumes:` 块给每个卷加 `name:` 字段固化命名，防止被项目名前缀污染 |
| `UniPortal/src/pages/tools/ToolsCenter.vue` | 工具中心 `<a target="_blank">` href 拼接 `portal_project_id`（**生效的真实入口，必改**） |
| `UniPortal/src/pages/tools/ToolViewer.vue` | iframe `src` 拼接 `portal_project_id`（备选 iframe 入口，按需改） |

### 9.3 接入新子工具的最短路径

1. 复制 `testcase-gen/docker-compose.yml`，改容器名、端口、镜像名
2. 在子工具代码里加 `UNIPORTAL_MODE` 分支（参照 9.1 第二行）
3. list 接口接受 `portal_project_id` 过滤（参照 §4.3）
4. 前端从 URL query 读参数 + 调接口时带上（参照 §5.3）
5. UniPortal 端不用动（`ToolsCenter.vue` 改造已经对所有子工具生效）
6. 按 §六 顺序启动，按 §七 验证清单核对

---

## 十、核心两句话

> **写操作只能动私有卷，共享卷一律只读。**
> **读操作先查私有再查共享卷，列表把两边合并。**
