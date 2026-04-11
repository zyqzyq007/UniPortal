import os
import shutil
import uuid
import zipfile
from datetime import datetime
from fastapi import UploadFile, HTTPException
from typing import List, Tuple

# 源码读取目录：集成模式下指向共享卷（只读），独立模式下指向本地 workspaces/
WORKSPACES_DIR = os.path.abspath(os.getenv("UNIPORTAL_STORAGE_PATH", "workspaces"))
# 集成模式标志：由 UNIPORTAL_STORAGE_PATH 是否被设置决定
UNIPORTAL_MODE = bool(os.getenv("UNIPORTAL_STORAGE_PATH"))
# 本工具私有可读写目录：存放缓存、图谱、CPG 等生成物（独立模式与 WORKSPACES_DIR 相同）
LOCAL_WORKSPACES_DIR = os.path.abspath(os.getenv("LOCAL_WORKSPACES_DIR", "workspaces"))

import json

class ProjectService:
    @staticmethod
    async def create_project(file: UploadFile, project_name: str = None) -> Tuple[str, str, int]:
        project_id = f"proj_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
        # 集成模式下写入本工具私有的可读写目录，避免写入只读的共享卷
        save_dir = LOCAL_WORKSPACES_DIR if UNIPORTAL_MODE else WORKSPACES_DIR
        project_dir = os.path.join(save_dir, project_id)
        os.makedirs(project_dir, exist_ok=True)

        if not project_name:
            project_name = file.filename.split('.')[0]

        file_location = os.path.join(project_dir, file.filename)
        
        # Save uploaded file
        with open(file_location, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        file_count = 0
        if file.filename.endswith(".zip"):
            with zipfile.ZipFile(file_location, 'r') as zip_ref:
                zip_ref.extractall(project_dir)
            # Remove the zip file after extraction
            os.remove(file_location)
            
            # Count files
            for root, dirs, files in os.walk(project_dir):
                for f in files:
                    if f.endswith(('.c', '.h')):
                        file_count += 1
        else:
            # Single file
            if file.filename.endswith(('.c', '.h')):
                file_count = 1
            else:
                # Should we reject? For now allow but count is 0 if not c/h
                pass

        # Scan for function design documents (JSON files with function_design structure)
        design_docs = {}
        for root, dirs, files in os.walk(project_dir):
            for f in files:
                if not f.endswith('.json') or f == 'meta.json':
                    continue
                json_path = os.path.join(root, f)
                try:
                    with open(json_path, 'r', encoding='utf-8') as jf:
                        data = json.load(jf)
                    # Support both {"function_design": {...}} and direct array/list of such objects
                    entries = []
                    if isinstance(data, dict) and 'function_design' in data:
                        entries = [data]
                    elif isinstance(data, list):
                        entries = [item for item in data if isinstance(item, dict) and 'function_design' in item]
                    for entry in entries:
                        fd = entry['function_design']
                        fname = fd.get('basic_info', {}).get('function_name', '').strip()
                        if fname:
                            design_docs[fname] = fd
                except Exception:
                    pass

        # Save metadata
        meta = {
            "project_name": project_name,
            "created_at": datetime.now().isoformat(),
            "original_filename": file.filename,
            "design_docs": design_docs
        }
        with open(os.path.join(project_dir, "meta.json"), "w") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        return project_id, project_name, file_count

    @staticmethod
    def get_function_design_doc(project_id: str, function_name: str) -> dict:
        """
        按函数名查找项目中的设计文档（function_design 结构）。
        优先从 meta.json 中读取上传时扫描到的 design_docs，
        若 meta.json 不含该字段则实时扫描项目目录中的 JSON 文件。
        返回 function_design 字典，未找到则返回 None。
        """
        if not function_name:
            return None
        # Try reading from meta.json first (fastest path)
        base_dir = LOCAL_WORKSPACES_DIR if UNIPORTAL_MODE else WORKSPACES_DIR
        meta_path = os.path.join(base_dir, project_id, "meta.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                if 'design_docs' in meta and function_name in meta['design_docs']:
                    return meta['design_docs'][function_name]
            except Exception:
                pass
        # Fallback: live scan of JSON files in the project directory
        try:
            project_dir = ProjectService.get_project_path(project_id)
        except Exception:
            return None
        for root, dirs, files in os.walk(project_dir):
            for fname in files:
                if not fname.endswith('.json') or fname == 'meta.json':
                    continue
                json_path = os.path.join(root, fname)
                try:
                    with open(json_path, 'r', encoding='utf-8') as jf:
                        data = json.load(jf)
                    entries = []
                    if isinstance(data, dict) and 'function_design' in data:
                        entries = [data]
                    elif isinstance(data, list):
                        entries = [item for item in data if isinstance(item, dict) and 'function_design' in item]
                    for entry in entries:
                        fd = entry['function_design']
                        if fd.get('basic_info', {}).get('function_name', '').strip() == function_name:
                            return fd
                except Exception:
                    pass
        return None

    @staticmethod
    def has_design_doc(project_id: str) -> bool:
        """
        判断该项目是否包含任意设计文档（meta.json 里的 design_docs 非空，
        或者项目目录下有含 function_design 结构的 JSON 文件）。
        """
        base_dir = LOCAL_WORKSPACES_DIR if UNIPORTAL_MODE else WORKSPACES_DIR
        meta_path = os.path.join(base_dir, project_id, "meta.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                if meta.get('design_docs'):
                    return True
            except Exception:
                pass
        # Fallback: live scan
        try:
            project_dir = ProjectService.get_project_path(project_id)
        except Exception:
            return False
        for root, _, files in os.walk(project_dir):
            for fname in files:
                if not fname.endswith('.json') or fname == 'meta.json':
                    continue
                try:
                    with open(os.path.join(root, fname), 'r', encoding='utf-8') as jf:
                        data = json.load(jf)
                    if isinstance(data, dict) and 'function_design' in data:
                        return True
                    if isinstance(data, list) and any(
                        isinstance(i, dict) and 'function_design' in i for i in data
                    ):
                        return True
                except Exception:
                    pass
        return False

    @staticmethod
    def get_local_project_dir(project_id: str) -> str:
        """
        返回本工具私有的可读写目录（用于存 cpg.bin、graphs/、_cache/ 等生成物）。
        集成模式：LOCAL_WORKSPACES_DIR/{project_id}（挂载到读写卷）
        独立模式：与 get_project_path 相同
        """
        local_dir = os.path.join(LOCAL_WORKSPACES_DIR, project_id)
        os.makedirs(local_dir, exist_ok=True)
        return local_dir

    @staticmethod
    def _build_item_index() -> dict:
        """
        集成模式专用：遍历共享卷两层目录，建立
          { item_id: abs_item_path } 的索引
        目录结构：{portal_project_id}/{item_id}/{zip解压文件夹}/源码
        """
        index = {}
        if not os.path.exists(WORKSPACES_DIR):
            return index
        for proj_dir in os.listdir(WORKSPACES_DIR):
            proj_path = os.path.join(WORKSPACES_DIR, proj_dir)
            if not os.path.isdir(proj_path) or proj_dir.startswith('.'):
                continue
            for item_id in os.listdir(proj_path):
                item_path = os.path.join(proj_path, item_id)
                if os.path.isdir(item_path) and not item_id.startswith(('.', '_')):
                    index[item_id] = item_path
        return index

    @staticmethod
    def get_project_path(project_id: str) -> str:
        if UNIPORTAL_MODE:
            # 先查本工具私有目录（用户自行上传的项目）
            local_path = os.path.join(LOCAL_WORKSPACES_DIR, project_id)
            if os.path.exists(local_path):
                return local_path
            # 再通过索引查 UniPortal 共享卷中的项目
            index = ProjectService._build_item_index()
            path = index.get(project_id)
            if not path or not os.path.exists(path):
                raise HTTPException(status_code=404, detail="Project not found")
            return path
        else:
            path = os.path.join(WORKSPACES_DIR, project_id)
            if not os.path.exists(path):
                raise HTTPException(status_code=404, detail="Project not found")
            return path

    @staticmethod
    def list_files(project_id: str) -> List[str]:
        project_dir = ProjectService.get_project_path(project_id)
        file_paths = []
        for root, _, files in os.walk(project_dir):
            for file in files:
                if file.endswith(('.c', '.h', '.json')):
                    # Skip meta.json at the project root
                    full = os.path.join(root, file)
                    rel_path = os.path.relpath(full, project_dir)
                    if rel_path == 'meta.json':
                        continue
                    file_paths.append(rel_path)
        return sorted(file_paths)

    @staticmethod
    def get_file_content(project_id: str, file_path: str) -> str:
        project_dir = ProjectService.get_project_path(project_id)
        # Prevent directory traversal
        full_path = os.path.abspath(os.path.join(project_dir, file_path))
        if not full_path.startswith(project_dir):
             raise HTTPException(status_code=400, detail="Invalid file path")
        
        if not os.path.exists(full_path):
            raise HTTPException(status_code=404, detail="File not found")
            
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    @staticmethod
    def get_project_name(project_id: str) -> str:
        # 集成模式下本地上传的项目存放在 LOCAL_WORKSPACES_DIR
        base_dir = LOCAL_WORKSPACES_DIR if UNIPORTAL_MODE else WORKSPACES_DIR
        project_dir = os.path.join(base_dir, project_id)
        meta_path = os.path.join(project_dir, "meta.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r") as f:
                    meta = json.load(f)
                    return meta.get("project_name", project_id)
            except:
                pass
        
        # Fallback for old projects: try to find a meaningful name
        try:
            items = os.listdir(project_dir)
            # 1. If there's a single directory, use it
            dirs = [d for d in items if os.path.isdir(os.path.join(project_dir, d)) and not d.startswith(('_', '.'))]
            if len(dirs) == 1:
                return dirs[0]
            
            # 2. Look for any .c file and use its parent directory name if it's not the project root
            for root, _, files in os.walk(project_dir):
                c_files = [f for f in files if f.endswith('.c')]
                if c_files:
                    rel_dir = os.path.relpath(root, project_dir)
                    if rel_dir != '.':
                        return rel_dir.split(os.sep)[0]
                    return c_files[0].split('.')[0]
        except:
            pass

        # 3. Last resort: use the random part of the ID instead of the date
        parts = project_id.split('_')
        return parts[-1] if len(parts) > 1 else project_id

    @staticmethod
    def delete_project(project_id: str) -> bool:
        if UNIPORTAL_MODE:
            # 集成模式下只允许删除本工具私有目录中用户自行上传的项目
            local_path = os.path.join(LOCAL_WORKSPACES_DIR, project_id.strip())
            if not os.path.exists(local_path):
                raise HTTPException(
                    status_code=403,
                    detail="集成模式下不允许删除 UniPortal 项目，请通过 UniPortal 管理。"
                )
            try:
                shutil.rmtree(local_path)
                return True
            except Exception as e:
                print(f"Error deleting project {project_id}: {e}")
                return False
        # Debug logging
        print(f"DEBUG: Attempting to delete project_id: {repr(project_id)}")
        
        # Clean up project_id just in case (strip whitespace/newlines)
        project_id = project_id.strip()
        
        project_dir = os.path.join(WORKSPACES_DIR, project_id)
        print(f"DEBUG: Target directory: {project_dir}, Exists: {os.path.exists(project_dir)}")
        
        if not os.path.exists(project_dir):
            return False
        try:
            shutil.rmtree(project_dir)
            return True
        except Exception as e:
            print(f"Error deleting project {project_id}: {e}")
            return False

    @staticmethod
    def list_projects() -> List[dict]:
        if not os.path.exists(WORKSPACES_DIR):
            return []

        projects = []

        if UNIPORTAL_MODE:
            # 集成模式：目录结构为 {portal_project_id}/{item_id}/{zip解压文件夹}/源码
            # project_id = item_id（单段 UUID，不含斜杠，URL 路由安全）
            # project_name = item 下第一层子文件夹名（即 zip 解压出的文件夹名）
            index = ProjectService._build_item_index()
            for item_id, item_path in sorted(index.items()):
                file_count = 0
                display_name = item_id  # 兜底用 item_id
                try:
                    sub_dirs = [
                        d for d in os.listdir(item_path)
                        if os.path.isdir(os.path.join(item_path, d))
                        and not d.startswith(('.', '_'))
                    ]
                    if sub_dirs:
                        display_name = sub_dirs[0]  # 取第一个子目录名作为展示名
                except Exception:
                    pass
                for root, _, files in os.walk(item_path):
                    for f in files:
                        if f.endswith(('.c', '.h')):
                            file_count += 1
                projects.append({
                    "project_id": item_id,
                    "project_name": display_name,
                    "file_count": file_count,
                    "status": "available"
                })

            # 合并本工具私有目录中用户自行上传的项目（proj_ 前缀）
            if os.path.exists(LOCAL_WORKSPACES_DIR):
                for d in os.listdir(LOCAL_WORKSPACES_DIR):
                    path = os.path.join(LOCAL_WORKSPACES_DIR, d)
                    if os.path.isdir(path) and d.startswith("proj_"):
                        file_count = 0
                        for root, _, files in os.walk(path):
                            for f in files:
                                if f.endswith(('.c', '.h')):
                                    file_count += 1
                        project_name = ProjectService.get_project_name(d)
                        projects.append({
                            "project_id": d,
                            "project_name": project_name,
                            "file_count": file_count,
                            "status": "available"
                        })
        else:
            # 独立模式：目录结构为 proj_YYYYMMDD_xxxx/
            for d in os.listdir(WORKSPACES_DIR):
                path = os.path.join(WORKSPACES_DIR, d)
                if os.path.isdir(path) and d.startswith("proj_"):
                    file_count = 0
                    for root, _, files in os.walk(path):
                        for f in files:
                            if f.endswith(('.c', '.h')):
                                file_count += 1
                    project_name = ProjectService.get_project_name(d)
                    projects.append({
                        "project_id": d,
                        "project_name": project_name,
                        "file_count": file_count,
                        "status": "available"
                    })
            projects = sorted(projects, key=lambda x: x['project_id'], reverse=True)

        return projects
