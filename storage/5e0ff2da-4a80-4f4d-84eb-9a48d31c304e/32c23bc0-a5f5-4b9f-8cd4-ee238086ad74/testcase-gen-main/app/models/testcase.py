from pydantic import BaseModel
from typing import List, Dict, Optional, Any

class GenerateTestRequest(BaseModel):
    project_id: str
    function_id: str
    test_framework: str = "unity"
    failure_context: Optional[str] = None
    function_intent: Optional[str] = None
    failed_task_id: Optional[str] = None

class AnnotateTestRequest(BaseModel):
    """第二步：基于设计文档给已有测试代码插入中文注释"""
    project_id: str
    function_id: str
    task_id: str  # 第一步生成的 task_id

class GenerateIntentRequest(BaseModel):
    project_id: str
    function_id: str

class GenerateIntentResponse(BaseModel):
    intent: str

class GenerateTestResponse(BaseModel):
    task_id: str
    test_code: str
    status: str

class ExecuteTestRequest(BaseModel):
    task_id: str

class TestCoverageDetail(BaseModel):
    covered: int
    total: int
    rate: float

class FunctionCoverageDetail(BaseModel):
    name: str
    line: TestCoverageDetail
    branch: TestCoverageDetail

class FileCoverage(BaseModel):
    file: str
    line: TestCoverageDetail
    function: TestCoverageDetail
    branch: TestCoverageDetail
    functions: Optional[List[FunctionCoverageDetail]] = []
    lines: Optional[Dict[int, int]] = {}  # Map line number to execution count


class TestCoverage(BaseModel):
    scope: str
    files: List[FileCoverage]

class TestResultDetail(BaseModel):
    passed: int
    failed: int
    total: int

class ExecuteTestResponse(BaseModel):
    task_id: str
    compile_success: bool
    execution_started: bool
    test_result: Optional[TestResultDetail] = None
    coverage: Optional[TestCoverage] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    source_code: Optional[str] = None
    function_start_line: Optional[int] = None
    function_end_line: Optional[int] = None  # Add this field
