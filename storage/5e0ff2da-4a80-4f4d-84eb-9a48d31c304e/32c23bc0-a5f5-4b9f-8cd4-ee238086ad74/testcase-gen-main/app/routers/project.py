from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Form
from fastapi.responses import FileResponse
from typing import List, Optional
import base64
import os

from app.services.project_service import ProjectService
from app.services.parser_service import ParserService
from app.services.joern_service import JoernService
from app.models.project import UploadResponse, ProjectStructure, FileStructure, FunctionInfo, ExtractTestTargetsResponse, TestTargetStats

router = APIRouter(prefix="/api/project", tags=["project"])

@router.post("/upload", response_model=UploadResponse)
async def upload_project(
    file: UploadFile = File(...),
    project_name: Optional[str] = Form(None)
):
    project_id, name, count = await ProjectService.create_project(file, project_name)
    return UploadResponse(
        project_id=project_id,
        project_name=name,
        file_count=count,
        status="uploaded"
    )

@router.get("/list", response_model=List[UploadResponse])
async def list_projects():
    projects = ProjectService.list_projects()
    return [UploadResponse(**p) for p in projects]

@router.delete("/{project_id}")
async def delete_project(project_id: str):
    success = ProjectService.delete_project(project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found or could not be deleted")
    return {"status": "success", "project_id": project_id}

@router.get("/{project_id}/has-design-doc")
async def has_design_doc(project_id: str):
    """判断项目是否包含任意设计文档（供前端决定是否执行第二步注释生成）"""
    return {"has_design_doc": ProjectService.has_design_doc(project_id)}

@router.get("/{project_id}/structure", response_model=ProjectStructure)
async def get_project_structure(project_id: str):
    files = ProjectService.list_files(project_id)
    structure = []
    
    for path in files:
        # Use path as file_id (base64 encoded to be safe)
        file_id = base64.urlsafe_b64encode(path.encode()).decode()
        ext = os.path.splitext(path)[1].lstrip('.')  # "c", "h", "json", …

        if ext == 'json':
            # JSON design-doc files: no function parsing, just expose for viewing
            structure.append(FileStructure(
                file_id=file_id,
                path=path,
                file_type='json',
                functions=[]
            ))
            continue

        try:
            content = ProjectService.get_file_content(project_id, path)
            functions = ParserService.parse_functions(content, file_id)
        except Exception:
            functions = []
            
        structure.append(FileStructure(
            file_id=file_id,
            path=path,
            file_type=ext or 'c',
            functions=functions
        ))
        
    return ProjectStructure(
        project_id=project_id,
        files=structure
    )

@router.get("/{project_id}/test-targets", response_model=ExtractTestTargetsResponse)
async def get_test_targets(
    project_id: str,
    include_optional_static: bool = Query(True),
    include_skipped: bool = Query(False),
    header_strategy: str = Query("basename")
):
    result = ParserService.extract_test_targets(project_id, header_strategy=header_strategy)

    optional_static = result.optional_static if include_optional_static else []
    skipped = result.skipped if include_skipped else []

    return ExtractTestTargetsResponse(
        project_id=project_id,
        must_test=result.must_test,
        optional_static=optional_static,
        skipped=skipped,
        stats=TestTargetStats(
            must_test_count=len(result.must_test),
            optional_static_count=len(optional_static),
            skipped_count=len(skipped)
        )
    )

@router.get("/{project_id}/test-summary")
async def get_test_summary(project_id: str):
    """
    Returns aggregated test results for the project from cache.
    Includes function coverage, pass/fail status, and task links.
    """
    from app.services.cache_service import CacheService
    
    # 1. Get all test targets (to know what we should have)
    targets_res = ParserService.extract_test_targets(project_id)
    must_test = targets_res.must_test
    
    summary = []
    
    for func in must_test:
        # 2. Query Cache for each function
        cache_data = CacheService.get_function_data(project_id, func.source_file, func.name)
        
        # Build summary item
        item = {
            "function_id": func.function_id,
            "name": func.name,
            "signature": func.signature,
            "source_file": func.source_file,
            "task_id": cache_data.get("latest_task_id"),
            "last_run": cache_data.get("last_execution_time"),
            "compile_success": cache_data.get("compile_success"),
            "passed": cache_data.get("passed", 0),
            "failed": cache_data.get("failed", 0),
            "ignored": cache_data.get("ignored", 0),
            "line_coverage": cache_data.get("line_coverage", 0.0),
            "branch_coverage": cache_data.get("branch_coverage", 0.0),
            "status": "unknown"
        }
        
        # Determine Status
        if not item["task_id"]:
            item["status"] = "pending"
        elif item["compile_success"] is False:
            item["status"] = "compile_error"
        elif item["failed"] > 0:
            item["status"] = "failed"
        elif item["passed"] > 0:
            item["status"] = "passed"
        elif item["ignored"] > 0:
            item["status"] = "ignored"
        else:
            item["status"] = "no_tests"
            
        summary.append(item)
        
    # Sort by coverage descending, then by status
    summary.sort(key=lambda x: (x["line_coverage"] or 0, x["passed"] or 0), reverse=True)
    
    return {
        "project_id": project_id,
        "total_functions": len(must_test),
        "functions": summary
    }

@router.get("/{project_id}/file")
async def get_file_source(project_id: str, file_id: str = Query(...)):
    try:
        path = base64.urlsafe_b64decode(file_id).decode()
    except:
        raise HTTPException(status_code=400, detail="Invalid file_id")
        
    content = ProjectService.get_file_content(project_id, path)
    return {
        "file_id": file_id,
        "path": path,
        "content": content
    }

@router.get("/{project_id}/graph/{image_name}")
async def get_project_graph(project_id: str, image_name: str):
    """
    Serves a generated graph image for a project.
    图片生成在本工具私有可写目录中，不在只读的共享卷里。
    """
    local_dir = ProjectService.get_local_project_dir(project_id)
    image_path = os.path.join(local_dir, "graphs", image_name)

    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="Graph image not found")

    return FileResponse(image_path)

@router.get("/{project_id}/function/{function_id}")
async def get_function_detail(project_id: str, function_id: str, use_joern: bool = Query(False), refresh: bool = Query(False)):
    # function_id format: file_id_startline
    try:
        parts = function_id.rsplit('_', 1)
        if len(parts) != 2:
            raise ValueError
        file_id = parts[0]
        start_line = int(parts[1])
        
        path = base64.urlsafe_b64decode(file_id).decode()
    except:
        raise HTTPException(status_code=400, detail="Invalid function_id format")
        
    content = ProjectService.get_file_content(project_id, path)
    functions = ParserService.parse_functions(content, file_id)
    
    target_func = None
    for f in functions:
        if f.start_line == start_line:
            target_func = f
            break
            
    if not target_func:
        raise HTTPException(status_code=404, detail="Function not found")
        
    # Extract source code for function
    lines = content.split('\n')
    # lines are 0-indexed, start_line is 1-indexed
    func_lines = lines[target_func.start_line-1 : target_func.end_line]
    source_code = "\n".join(func_lines)
    
    if use_joern:
        code_graph = await ParserService.generate_joern_graph(project_id, target_func.name, depth=3, refresh=refresh)
        # Fallback to regex if Joern fails or returns empty
        if not code_graph or not code_graph.get("calls"):
            print("Joern failed, using regex fallback")
            code_graph = ParserService.generate_code_graph(source_code)
    else:
        code_graph = ParserService.generate_code_graph(source_code)
    
    return {
        "function_id": function_id,
        "name": target_func.name,
        "signature": target_func.signature,
        "start_line": target_func.start_line,
        "end_line": target_func.end_line,
        "source_code": source_code
    }

@router.get("/{project_id}/function/{function_id}/graph")
async def get_function_graph(project_id: str, function_id: str, use_joern: bool = Query(False), refresh: bool = Query(False)):
    # Legacy endpoint for backward compatibility or bulk fetch
    try:
        parts = function_id.rsplit('_', 1)
        if len(parts) != 2: raise ValueError
        file_id = parts[0]
        start_line = int(parts[1])
        path = base64.urlsafe_b64decode(file_id).decode()
    except:
        raise HTTPException(status_code=400, detail="Invalid function_id format")
        
    content = ProjectService.get_file_content(project_id, path)
    functions = ParserService.parse_functions(content, file_id)
    target_func = next((f for f in functions if f.start_line == start_line), None)
            
    if not target_func:
        raise HTTPException(status_code=404, detail="Function not found")
        
    lines = content.split('\n')
    func_lines = lines[target_func.start_line-1 : target_func.end_line]
    source_code = "\n".join(func_lines)
    
    if use_joern:
        code_graph = await ParserService.generate_joern_graph(project_id, target_func.name, depth=3, refresh=refresh)
        if not code_graph or (not code_graph.get("calls") and not code_graph.get("graph_image")):
            code_graph = ParserService.generate_code_graph(source_code)
    else:
        code_graph = ParserService.generate_code_graph(source_code)
    
    return code_graph

@router.get("/{project_id}/function/{function_id}/graph/{graph_type}")
async def get_specific_graph(project_id: str, function_id: str, graph_type: str, refresh: bool = Query(False)):
    """
    Generate and get a specific type of graph: call, ast, cfg, pdg
    """
    try:
        parts = function_id.rsplit('_', 1)
        file_id = parts[0]
        start_line = int(parts[1])
        path = base64.urlsafe_b64decode(file_id).decode()
    except:
        raise HTTPException(status_code=400, detail="Invalid function_id format")

    content = ProjectService.get_file_content(project_id, path)
    functions = ParserService.parse_functions(content, file_id)
    target_func = next((f for f in functions if f.start_line == start_line), None)
    if not target_func:
        raise HTTPException(status_code=404, detail="Function not found")

    # 源码路径（可能只读），图谱/CPG 写到本工具私有可写目录
    source_dir = ProjectService.get_project_path(project_id)
    local_dir = ProjectService.get_local_project_dir(project_id)
    cpg_path = os.path.join(local_dir, "cpg.bin")

    # Joern 解析源码目录，但输出到可写的 local_dir
    await JoernService.parse_project(source_dir, cpg_path)

    image_path = None
    if graph_type == "call":
        image_path = await JoernService.generate_graph_image(local_dir, target_func.name, refresh=refresh)
    elif graph_type == "ast":
        image_path = await JoernService.generate_ast_image(local_dir, target_func.name, refresh=refresh)
    elif graph_type == "cfg":
        image_path = await JoernService.generate_cfg_image(local_dir, target_func.name, refresh=refresh)
    elif graph_type == "pdg":
        image_path = await JoernService.generate_pdg_image(local_dir, target_func.name, refresh=refresh)
    else:
        raise HTTPException(status_code=400, detail="Unsupported graph type")

    # Get mtime for browser caching
    mtime = 0
    if image_path:
        full_path = os.path.join(local_dir, "graphs", image_path)
        if os.path.exists(full_path):
            mtime = int(os.path.getmtime(full_path))

    return {"type": graph_type, "image": image_path, "mtime": mtime}
