import os
import json
import hashlib
import base64
from datetime import datetime
from typing import Optional, Dict, Any

CACHE_DIR = os.path.abspath("workspaces/_cache") # Legacy/Global cache if needed
# 缓存写入本工具私有可读写目录，避免写到只读的共享卷
WORKSPACES_DIR = os.path.abspath(os.getenv("LOCAL_WORKSPACES_DIR", "workspaces"))

class CacheService:
    @staticmethod
    def _get_cache_path(project_id: str, file_path: str, function_name: str) -> str:
        # Use project-specific cache directory: workspaces/<project_id>/_cache
        project_cache_dir = os.path.join(WORKSPACES_DIR, project_id, "_cache")
        os.makedirs(project_cache_dir, exist_ok=True)
        
        # Create a stable hash for the file path to avoid filesystem issues with long paths/slashes
        # function_name is usually safe, but let's hash the combination for safety
        key = f"{file_path}::{function_name}"
        file_hash = hashlib.md5(key.encode()).hexdigest()
        
        return os.path.join(project_cache_dir, f"{file_hash}.json")

    @staticmethod
    def save_function_data(project_id: str, file_path: str, function_name: str, data: Dict[str, Any]):
        """
        Updates the cache for a specific function. Merges with existing data.
        """
        path = CacheService._get_cache_path(project_id, file_path, function_name)
        
        existing_data = {}
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    existing_data = json.load(f)
            except:
                pass
        
        # Merge new data
        existing_data.update(data)
        existing_data["updated_at"] = str(datetime.now())
        
        with open(path, 'w') as f:
            json.dump(existing_data, f, indent=2)

    @staticmethod
    def get_function_data(project_id: str, file_path: str, function_name: str) -> Dict[str, Any]:
        path = CacheService._get_cache_path(project_id, file_path, function_name)
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
