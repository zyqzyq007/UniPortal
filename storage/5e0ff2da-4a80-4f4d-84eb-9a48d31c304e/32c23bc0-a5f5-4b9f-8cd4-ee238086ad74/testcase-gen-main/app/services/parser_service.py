import re
import os
import base64
from typing import List, Dict, Any, Optional
from app.models.project import FunctionInfo, TestTargetFunctionInfo, ExtractTestTargetsResponse, TestTargetStats
from app.services.joern_service import JoernService
from app.services.project_service import ProjectService

class ParserService:
    @staticmethod
    def parse_functions(content: str, file_id: str) -> List[FunctionInfo]:
        """
        Extracts function definitions using regex and brace counting.
        """
        lines = content.split('\n')
        functions = []
        
        # More robust regex for function start
        # Matches: [type] [stars] [name] ( [args] )
        # Updated to handle multi-word return types (e.g., unsigned int, struct Foo)
        # It captures the LAST word before the parenthesis as the function name
        func_start_pattern = re.compile(r'^(?:static\s+|inline\s+|extern\s+)*(?:[a-zA-Z0-9_]+\s*\*?\s+)+([a-zA-Z0-9_]+)\s*\(([^)]*)\)')
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line or line.startswith(('#', '//', '/*', '*', '}') ):
                i += 1
                continue

            match = func_start_pattern.match(line)
            
            if match:
                func_name = match.group(1)
                if func_name in ['if', 'while', 'for', 'switch', 'return', 'sizeof', 'typedef', 'struct']:
                    i += 1
                    continue
                
                # Look for the opening brace, possibly on subsequent lines
                start_line = i + 1
                brace_found = False
                current_line_idx = i
                
                # Check current line first
                if '{' in lines[i]:
                    brace_found = True
                else:
                    # Check next few lines (limit to 5 lines to avoid false positives)
                    for k in range(1, 6):
                        if i + k < len(lines):
                            next_line = lines[i+k].strip()
                            if not next_line: continue
                            if next_line.startswith('{'):
                                brace_found = True
                                current_line_idx = i + k
                                break
                            if next_line.startswith((';', '#')) or '(' in next_line: # Likely a declaration or macro
                                break
                
                if not brace_found:
                    i += 1
                    continue

                # Now scan for end of function using brace counting
                brace_count = 0
                opened = False
                end_line = -1
                
                for j in range(current_line_idx, len(lines)):
                    l = lines[j]
                    # Simple brace counting, ignoring braces in strings/comments (naive)
                    # For better accuracy, we'd need a real lexer, but this is usually okay for C
                    brace_count += l.count('{') - l.count('}')
                    if not opened and '{' in l:
                        opened = True
                    
                    if opened and brace_count <= 0:
                        end_line = j + 1
                        break
                
                if end_line != -1:
                    functions.append(FunctionInfo(
                        function_id=f"{file_id}_{start_line}",
                        name=func_name,
                        start_line=start_line,
                        end_line=end_line,
                        signature=line.rstrip('{').strip()
                    ))
                    i = end_line
                    continue
            i += 1
            
        return functions

    @staticmethod
    def _strip_c_comments(text: str) -> str:
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
        text = re.sub(r'//.*?$', '', text, flags=re.M)
        return text

    @staticmethod
    def _is_static_signature(signature: str) -> bool:
        return bool(re.match(r'^\s*static\b', signature or ""))

    @staticmethod
    def header_declares_function(header_content: str, function_name: str) -> bool:
        if not header_content or not function_name:
            return False
        clean = ParserService._strip_c_comments(header_content)
        clean = re.sub(r'^\s*#.*$', '', clean, flags=re.M)
        pattern = re.compile(r'(^|[^\w])' + re.escape(function_name) + r'\s*\([^;{}]*\)\s*;', flags=re.M)
        return bool(pattern.search(clean))

    @staticmethod
    def extract_test_targets(
        project_id: str,
        header_strategy: str = "basename"
    ) -> ExtractTestTargetsResponse:
        files = ProjectService.list_files(project_id)
        c_files = [p for p in files if p.lower().endswith(".c")]
        h_files = [p for p in files if p.lower().endswith(".h")]

        header_content_by_path: Dict[str, str] = {}
        header_paths_by_basename: Dict[str, List[str]] = {}

        for h_path in h_files:
            try:
                header_content_by_path[h_path] = ProjectService.get_file_content(project_id, h_path)
            except Exception:
                header_content_by_path[h_path] = ""
            base = os.path.basename(h_path)
            header_paths_by_basename.setdefault(base, []).append(h_path)

        must_test: List[TestTargetFunctionInfo] = []
        optional_static: List[TestTargetFunctionInfo] = []
        skipped: List[TestTargetFunctionInfo] = []

        for c_path in c_files:
            file_id = base64.urlsafe_b64encode(c_path.encode()).decode()
            try:
                content = ProjectService.get_file_content(project_id, c_path)
                functions = ParserService.parse_functions(content, file_id)
            except Exception:
                continue

            same_basename_header = os.path.splitext(c_path)[0] + ".h"
            header_path = None
            if header_strategy == "basename":
                if same_basename_header in header_content_by_path:
                    header_path = same_basename_header
                else:
                    header_basename = os.path.basename(same_basename_header)
                    candidates = header_paths_by_basename.get(header_basename, [])
                    if len(candidates) == 1:
                        header_path = candidates[0]

            header_content = header_content_by_path.get(header_path, "") if header_path else ""

            for f in functions:
                is_static = ParserService._is_static_signature(f.signature)
                if is_static:
                    optional_static.append(TestTargetFunctionInfo(
                        function_id=f.function_id,
                        name=f.name,
                        start_line=f.start_line,
                        end_line=f.end_line,
                        signature=f.signature,
                        source_file=c_path,
                        category="internal_static",
                        header_file=header_path,
                        declared_in_header=False
                    ))
                    continue

                if not header_path:
                    # No corresponding header found — treat as must-test anyway
                    # (the function is non-static and externally linkable)
                    must_test.append(TestTargetFunctionInfo(
                        function_id=f.function_id,
                        name=f.name,
                        start_line=f.start_line,
                        end_line=f.end_line,
                        signature=f.signature,
                        source_file=c_path,
                        category="external_linkage",
                        header_file=None,
                        declared_in_header=False,
                        reason="no_corresponding_header"
                    ))
                    continue

                declared = ParserService.header_declares_function(header_content, f.name)
                if declared:
                    must_test.append(TestTargetFunctionInfo(
                        function_id=f.function_id,
                        name=f.name,
                        start_line=f.start_line,
                        end_line=f.end_line,
                        signature=f.signature,
                        source_file=c_path,
                        category="external_linkage",
                        header_file=header_path,
                        declared_in_header=True
                    ))
                else:
                    # Header exists but function not declared in it —
                    # still treat as must-test (non-static, externally linked)
                    must_test.append(TestTargetFunctionInfo(
                        function_id=f.function_id,
                        name=f.name,
                        start_line=f.start_line,
                        end_line=f.end_line,
                        signature=f.signature,
                        source_file=c_path,
                        category="external_linkage",
                        header_file=header_path,
                        declared_in_header=False,
                        reason="not_declared_in_header"
                    ))

        stats = TestTargetStats(
            must_test_count=len(must_test),
            optional_static_count=len(optional_static),
            skipped_count=len(skipped)
        )
        return ExtractTestTargetsResponse(
            project_id=project_id,
            must_test=must_test,
            optional_static=optional_static,
            skipped=skipped,
            stats=stats
        )

    @staticmethod
    def generate_code_graph(function_code: str) -> Dict[str, Any]:
        """
        Generates a simplified code graph using regex.
        """
        # 1. Extract variables (naive: arguments + basic declarations)
        variables = set()
        
        # Extract args from first line
        first_line = function_code.split('\n')[0]
        args_match = re.search(r'\(([^)]*)\)', first_line)
        if args_match:
            args_str = args_match.group(1)
            for arg in args_str.split(','):
                parts = arg.strip().split()
                if len(parts) >= 2:
                    variables.add(parts[-1].replace('*', ''))

        # Naive local var: "int a;" or "char *b;"
        local_var_pattern = re.compile(r'\b(int|char|float|double|long|short|void|bool)\s+[\*]*([a-zA-Z0-9_]+)\s*[;,=]')
        for match in local_var_pattern.finditer(function_code):
            variables.add(match.group(2))

        # 2. Extract Calls
        calls = set()
        call_pattern = re.compile(r'\b([a-zA-Z0-9_]+)\s*\(')
        for match in call_pattern.finditer(function_code):
            name = match.group(1)
            if name not in ['if', 'while', 'for', 'switch', 'return', 'sizeof']:
                 calls.add(name)

        # 3. Extract Returns
        returns = []
        return_pattern = re.compile(r'\breturn\s+(.*?);')
        for match in return_pattern.finditer(function_code):
            returns.append(match.group(1))

        return {
            "variables": list(variables),
            "calls": list(calls),
            "returns": returns,
            "branches": []
        }

    @staticmethod
    async def generate_joern_graph(project_id: str, function_name: str, depth: int = 3, refresh: bool = False) -> Dict[str, Any]:
        """
        Generates metadata for code graph using Joern CPG analysis.
        Images are NOT generated here to speed up metadata retrieval.
        """
        # 源码目录（可能只读），cpg.bin 写到本工具私有可写目录
        source_dir = ProjectService.get_project_path(project_id)
        local_dir = ProjectService.get_local_project_dir(project_id)
        cpg_path = os.path.join(local_dir, "cpg.bin")

        # 1. Parse project if needed
        success = await JoernService.parse_project(source_dir, cpg_path)
        if not success:
            return {}

        # 2. Query CPG for metadata (calls, variables, etc.)
        graph = await JoernService.get_function_cpg_depth(cpg_path, function_name, depth, refresh=refresh)
        
        # Define expected image paths
        call_graph_image_path = f"{function_name}_3layer.png"
        ast_image_path = f"{function_name}_ast.png"
        cfg_image_path = f"{function_name}_cfg.png"
        pdg_image_path = f"{function_name}_pdg.png"
        
        if graph:
            rich_calls = graph.get("calls", [])
            call_names = list(set([c["name"] for c in rich_calls]))
            
            return {
                "variables": graph.get("variables", []),
                "calls": call_names,
                "returns": graph.get("returns", []),
                "branches": [], 
                "rich_calls": rich_calls,
                "graph_image": call_graph_image_path,
                "ast_image": ast_image_path,
                "cfg_image": cfg_image_path,
                "pdg_image": pdg_image_path
            }
        
        return {
            "graph_image": call_graph_image_path,
            "ast_image": ast_image_path,
            "cfg_image": cfg_image_path,
            "pdg_image": pdg_image_path
        }
