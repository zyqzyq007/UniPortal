from pydantic import BaseModel
from typing import List, Optional, Dict

class FileInfo(BaseModel):
    file_id: str
    path: str
    content: Optional[str] = None

class FunctionInfo(BaseModel):
    function_id: str
    name: str
    start_line: int
    end_line: int
    signature: str

class FileStructure(BaseModel):
    file_id: str
    path: str
    file_type: Optional[str] = "c"   # "c", "h", "json", etc.
    functions: List[FunctionInfo]

class ProjectStructure(BaseModel):
    project_id: str
    files: List[FileStructure]

class UploadResponse(BaseModel):
    project_id: str
    project_name: str
    file_count: int
    status: str

class TestTargetFunctionInfo(BaseModel):
    function_id: str
    name: str
    start_line: int
    end_line: int
    signature: str
    source_file: str
    category: str
    header_file: Optional[str] = None
    declared_in_header: Optional[bool] = None
    reason: Optional[str] = None

class TestTargetStats(BaseModel):
    must_test_count: int
    optional_static_count: int
    skipped_count: int

class ExtractTestTargetsResponse(BaseModel):
    project_id: str
    must_test: List[TestTargetFunctionInfo]
    optional_static: List[TestTargetFunctionInfo]
    skipped: List[TestTargetFunctionInfo]
    stats: TestTargetStats
