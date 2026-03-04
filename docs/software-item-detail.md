# 软件项目详情页交付文档

## 组件 Props
- `SoftwareItemDetail`
  - 路由参数：`projectId`、`itemId`
  - 查询参数：`search`、`page`（用于返回列表状态保持）、`itemName`
- `SoftwareTreeNode`
  - `node`: 当前节点对象
  - `selectedPath`: 当前选中文件路径
  - `expandedMap`: 展开状态映射
  - `keyword`: 搜索关键词

## 事件列表
- `SoftwareTreeNode`
  - `open-file(node)`: 点击文件节点时触发
  - `toggle-dir(node)`: 展开/折叠目录时触发
  - `contextmenu(event, node)`: 右键菜单触发

## 目录树数据结构示例
```json
{
  "name": "DemoItem",
  "path": "",
  "type": "dir",
  "children": [
    {
      "name": "src",
      "type": "dir",
      "path": "src",
      "updated_at": "2026-03-04T10:20:30.000Z",
      "children": []
    },
    {
      "name": "README.md",
      "type": "file",
      "path": "README.md",
      "size": 1024,
      "updated_at": "2026-03-04T10:20:30.000Z"
    }
  ]
}
```

## 异常码对照表
- `400`：参数错误（如 path 缺失、路径不是文件/目录）
- `401`：未认证
- `403`：无权限访问工程或软件项目
- `404`：工程/软件项目/文件路径不存在
- `413`：文件超过 1MB，需要前端确认后分片加载
- `500`：服务内部错误

