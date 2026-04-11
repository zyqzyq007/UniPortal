import os
import json
import uuid
import shutil
import subprocess
import asyncio
import re
from datetime import datetime
from typing import Tuple, Dict, Any, Optional, List
from app.models.testcase import TestResultDetail, ExecuteTestResponse, TestCoverage, FileCoverage, TestCoverageDetail, FunctionCoverageDetail
from app.services.project_service import ProjectService

TASKS_DIR = os.path.abspath("workspaces/_tasks")
UNITY_SRC_DIR = os.path.abspath("resources/unity")

class RunnerService:
    @staticmethod
    def _parse_lcov_info(info_path: str, base_dir: str) -> List[FileCoverage]:
        files_coverage = []
        current_file = None
        
        # File-level counters
        l_total = 0; l_covered = 0
        b_total = 0; b_covered = 0
        f_total = 0; f_covered = 0
        
        # Function-level data mapping
        # function_map: {func_name: {'start_line': int, 'end_line': int, 'l_total': 0, 'l_covered': 0, ...}}
        # But LCOV info usually gives:
        # FN:line,name
        # FNDA:count,name
        # It DOES NOT give end_line. So it's hard to map lines to functions strictly from LCOV info alone 
        # without parsing source code or assuming functions are sequential.
        # However, typical approach is:
        # 1. Read FN records to know function start lines.
        # 2. Sort functions by start line.
        # 3. Assign lines/branches to the function with the nearest start line <= line number.
        
        functions_info = {} # name -> {'line': int, 'execution_count': int}
        lines_data = {} # line_no -> execution_count
        branches_data = {} # line_no -> list of taken counts
        
        if not os.path.exists(info_path):
            return []

        with open(info_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('SF:'):
                    current_file = line[3:]
                    l_total = 0; l_covered = 0
                    b_total = 0; b_covered = 0
                    f_total = 0; f_covered = 0
                    functions_info = {}
                    lines_data = {}
                    branches_data = {}
                    
                elif line.startswith('FN:'): # FN:line,name
                    parts = line[3:].split(',')
                    if len(parts) >= 2:
                        func_line = int(parts[0])
                        func_name = parts[1]
                        functions_info[func_name] = {'line': func_line, 'execution_count': 0}
                        # print(f"DEBUG: Found function {func_name} at line {func_line}")
                        
                elif line.startswith('FNDA:'): # FNDA:count,name
                    parts = line[5:].split(',')
                    if len(parts) >= 2:
                        count = int(parts[0])
                        func_name = parts[1]
                        if func_name in functions_info:
                            functions_info[func_name]['execution_count'] = count

                elif line.startswith('DA:'): # DA:line,count
                    parts = line[3:].split(',')
                    if len(parts) >= 2:
                        ln = int(parts[0])
                        cnt = int(parts[1])
                        lines_data[ln] = cnt
                        
                elif line.startswith('BRDA:'): # BRDA:line,block,branch,taken
                    parts = line[5:].split(',')
                    if len(parts) >= 4:
                        ln = int(parts[0])
                        taken = parts[3]
                        cnt = int(taken) if taken != '-' else 0
                        if ln not in branches_data:
                            branches_data[ln] = []
                        branches_data[ln].append(cnt)

                elif line == 'end_of_record':
                    if current_file and ("test_runner.c" not in current_file and "unity.c" not in current_file):
                        # Calculate File Totals
                        l_total = len(lines_data)
                        l_covered = sum(1 for c in lines_data.values() if c > 0)
                        
                        b_total = sum(len(brs) for brs in branches_data.values())
                        b_covered = sum(sum(1 for c in brs if c > 0) for brs in branches_data.values())
                        
                        f_total = len(functions_info)
                        f_covered = sum(1 for f in functions_info.values() if f['execution_count'] > 0)

                        # Calculate Function Details
                        # Sort functions by start line
                        sorted_funcs = sorted(functions_info.items(), key=lambda x: x[1]['line'])
                        func_details = []
                        # print(f"DEBUG: Processing {len(sorted_funcs)} functions for {current_file}")
                        
                        for i, (name, info) in enumerate(sorted_funcs):
                            start_line = info['line']
                            # End line is start of next function - 1, or infinity (max line in file)
                            if i < len(sorted_funcs) - 1:
                                end_line = sorted_funcs[i+1][1]['line'] - 1
                            else:
                                end_line = max(lines_data.keys()) if lines_data else start_line + 1000
                                
                            # Aggregate lines for this function
                            fl_total = 0; fl_covered = 0
                            fb_total = 0; fb_covered = 0
                            
                            for ln, cnt in lines_data.items():
                                if start_line <= ln <= end_line:
                                    fl_total += 1
                                    if cnt > 0: fl_covered += 1
                                    
                            for ln, brs in branches_data.items():
                                if start_line <= ln <= end_line:
                                    fb_total += len(brs)
                                    fb_covered += sum(1 for c in brs if c > 0)
                                    
                            func_details.append(FunctionCoverageDetail(
                                name=name,
                                line=TestCoverageDetail(covered=fl_covered, total=fl_total, rate=fl_covered/fl_total if fl_total else 1.0),
                                branch=TestCoverageDetail(covered=fb_covered, total=fb_total, rate=fb_covered/fb_total if fb_total else 1.0)
                            ))

                        # Calculate relative path from task_dir
                        rel_file = os.path.relpath(current_file, task_dir)
                        # If the project was copied into task_dir, we might want to keep the rel path
                        
                        files_coverage.append(FileCoverage(
                            file=rel_file,
                            line=TestCoverageDetail(covered=l_covered, total=l_total, rate=l_covered/l_total if l_total else 1.0),
                            function=TestCoverageDetail(covered=f_covered, total=f_total, rate=f_covered/f_total if f_total else 1.0),
                            branch=TestCoverageDetail(covered=b_covered, total=b_total, rate=b_covered/b_total if b_total else 1.0),
                            functions=func_details,
                            lines=lines_data  # Pass the line execution data
                        ))
        return files_coverage

    @staticmethod
    def _parse_gcov_file(gcov_path: str, source_file: str) -> FileCoverage:
        lines_total = 0
        lines_covered = 0
        branches_total = 0
        branches_covered = 0
        
        # Naive parsing of gcov output (or lcov .info if we switched to that)
        # But gcov .c.gcov files are textual.
        # Format:
        #        -:    0:Source:foo.c
        #        1:    1:int add(int a, int b) {
        #    #####:    2:    return a + b;
        # branch  0 taken 0% (fallthrough)
        # branch  1 taken 100%
        
        # However, getting branch info from plain gcov requires -b flag and parsing is tricky.
        # Let's use lcov as suggested by user for easier parsing? 
        # User said: "Parsing to your JSON... read .gcov or lcov output"
        # LCOV info format is easier to parse standardly.
        
        # Let's stick to gcov -b -c for now if we want text, OR use lcov -> coverage.info -> parse
        # LCOV flow:
        # lcov --capture --directory . --output-file coverage.info
        # Then parse coverage.info
        pass

    @staticmethod
    def _parse_lcov_info(info_path: str, base_dir: str) -> List[FileCoverage]:
        files_coverage = []
        current_file = None
        
        # File-level counters
        l_total = 0; l_covered = 0
        b_total = 0; b_covered = 0
        f_total = 0; f_covered = 0
        
        functions_info = {} # name -> {'line': int, 'execution_count': int}
        lines_data = {} # line_no -> execution_count
        branches_data = {} # line_no -> list of taken counts
        
        if not os.path.exists(info_path):
            return []

        with open(info_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('SF:'):
                    current_file = line[3:]
                    # Ensure current_file is absolute for relpath calculation if it's not
                    if not os.path.isabs(current_file):
                         current_file = os.path.join(base_dir, current_file)
                    
                    l_total = 0; l_covered = 0
                    b_total = 0; b_covered = 0
                    f_total = 0; f_covered = 0
                    functions_info = {}
                    lines_data = {}
                    branches_data = {}
                    
                elif line.startswith('FN:'): # FN:line,name
                    parts = line[3:].split(',')
                    if len(parts) >= 2:
                        func_line = int(parts[0])
                        func_name = parts[1]
                        functions_info[func_name] = {'line': func_line, 'execution_count': 0}
                        
                elif line.startswith('FNDA:'): # FNDA:count,name
                    parts = line[5:].split(',')
                    if len(parts) >= 2:
                        count = int(parts[0])
                        func_name = parts[1]
                        if func_name in functions_info:
                            functions_info[func_name]['execution_count'] = count

                elif line.startswith('DA:'): # DA:line,count
                    parts = line[3:].split(',')
                    if len(parts) >= 2:
                        ln = int(parts[0])
                        cnt = int(parts[1])
                        lines_data[ln] = cnt
                        
                elif line.startswith('BRDA:'): # BRDA:line,block,branch,taken
                    parts = line[5:].split(',')
                    if len(parts) >= 4:
                        ln = int(parts[0])
                        taken = parts[3]
                        cnt = int(taken) if taken != '-' else 0
                        if ln not in branches_data:
                            branches_data[ln] = []
                        branches_data[ln].append(cnt)

                elif line == 'end_of_record':
                    if current_file and ("test_runner.c" not in current_file and "unity.c" not in current_file):
                        # Calculate File Totals
                        l_total = len(lines_data)
                        l_covered = sum(1 for c in lines_data.values() if c > 0)
                        
                        b_total = sum(len(brs) for brs in branches_data.values())
                        b_covered = sum(sum(1 for c in brs if c > 0) for brs in branches_data.values())
                        
                        f_total = len(functions_info)
                        f_covered = sum(1 for f in functions_info.values() if f['execution_count'] > 0)

                        # Calculate Function Details
                        sorted_funcs = sorted(functions_info.items(), key=lambda x: x[1]['line'])
                        func_details = []
                        
                        for i, (name, info) in enumerate(sorted_funcs):
                            start_line = info['line']
                            if i < len(sorted_funcs) - 1:
                                end_line = sorted_funcs[i+1][1]['line'] - 1
                            else:
                                end_line = max(lines_data.keys()) if lines_data else start_line + 1000
                                
                            fl_total = 0; fl_covered = 0
                            fb_total = 0; fb_covered = 0
                            
                            for ln, cnt in lines_data.items():
                                if start_line <= ln <= end_line:
                                    fl_total += 1
                                    if cnt > 0: fl_covered += 1
                                    
                            for ln, brs in branches_data.items():
                                if start_line <= ln <= end_line:
                                    fb_total += len(brs)
                                    fb_covered += sum(1 for c in brs if c > 0)
                                    
                            func_details.append(FunctionCoverageDetail(
                                name=name,
                                line=TestCoverageDetail(covered=fl_covered, total=fl_total, rate=fl_covered/fl_total if fl_total else 1.0),
                                branch=TestCoverageDetail(covered=fb_covered, total=fb_total, rate=fb_covered/fb_total if fb_total else 1.0)
                            ))

                        # Calculate relative path from base_dir
                        try:
                            rel_file = os.path.relpath(current_file, base_dir)
                        except ValueError:
                            rel_file = os.path.basename(current_file)
                        
                        files_coverage.append(FileCoverage(
                            file=rel_file,
                            line=TestCoverageDetail(covered=l_covered, total=l_total, rate=l_covered/l_total if l_total else 1.0),
                            function=TestCoverageDetail(covered=f_covered, total=f_total, rate=f_covered/f_total if f_total else 1.0),
                            branch=TestCoverageDetail(covered=b_covered, total=b_total, rate=b_covered/b_total if b_total else 1.0),
                            functions=func_details,
                            lines=lines_data
                        ))
        return files_coverage
    @staticmethod
    def create_task(project_id: str, function_id: str, test_code: str, source_file_path: str, function_name: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
        task_id = str(uuid.uuid4())
        task_dir = os.path.join(TASKS_DIR, task_id)
        os.makedirs(task_dir, exist_ok=True)

        metadata = {
            "project_id": project_id,
            "function_id": function_id,
            "function_name": function_name,
            "source_file_path": source_file_path,
            "created_at": str(datetime.now()),
            "start_line": start_line,
            "end_line": end_line
        }
        
        with open(os.path.join(task_dir, "metadata.json"), "w") as f:
            json.dump(metadata, f)
            
        with open(os.path.join(task_dir, "test_runner.c"), "w") as f:
            f.write(test_code)
            
        return task_id

    @staticmethod
    def get_task_code(task_id: str) -> Optional[str]:
        task_dir = os.path.join(TASKS_DIR, task_id)
        code_path = os.path.join(task_dir, "test_runner.c")
        if not os.path.exists(code_path):
            return None
        with open(code_path, "r") as f:
            return f.read()

    @staticmethod
    def get_task_status(task_id: str) -> Dict[str, Any]:
        task_dir = os.path.join(TASKS_DIR, task_id)
        meta_path = os.path.join(task_dir, "metadata.json")
        if not os.path.exists(meta_path):
            return None
        with open(meta_path, "r") as f:
            return json.load(f)

    @staticmethod
    async def execute_task(task_id: str) -> ExecuteTestResponse:
        task_dir = os.path.join(TASKS_DIR, task_id)
        if not os.path.exists(task_dir):
            raise Exception("Task not found")
            
        with open(os.path.join(task_dir, "metadata.json"), "r") as f:
            metadata = json.load(f)
            
        # 1. Setup Environment
        # Copy Unity files
        if not os.path.exists(UNITY_SRC_DIR):
             pass
        else:
            for f in ["unity.h", "unity.c", "unity_internals.h"]:
                src = os.path.join(UNITY_SRC_DIR, f)
                if os.path.exists(src):
                    shutil.copy(src, task_dir)
        
        # 2. Prepare Source
        # Copy the entire project to task_dir to ensure headers and other dependencies are available
        project_dir = ProjectService.get_project_path(metadata["project_id"])
        # Use shutil.copytree with ignore to avoid copying binary artifacts
        def ignore_patterns(path, names):
            return [n for n in names if n.endswith(('.o', '.gcda', '.gcno', '.info')) or n == 'coverage.info' or n == 'runner']

        for item in os.listdir(project_dir):
            if item == "_tasks": continue
            s = os.path.join(project_dir, item)
            d = os.path.join(task_dir, item)
            if os.path.isdir(s):
                shutil.copytree(s, d, dirs_exist_ok=True, ignore=ignore_patterns)
            else:
                if not any(item.endswith(ext) for ext in ['.o', '.gcda', '.gcno', '.info']):
                    shutil.copy2(s, d)
        
        # The source file path is relative to project root
        target_file_rel = metadata["source_file_path"]
        function_name   = metadata.get("function_name", "")
        
        # 2.5 Make target file testable
        # Remove 'static' so internal functions are visible to the linker.
        # (We no longer inject __attribute__((weak)) at the source level because
        #  the regex approach is unreliable for complex C code.  Instead we use
        #  `objcopy --weaken-symbol` at the binary level after compilation — see
        #  the post-compile step below.)
        target_abs_path = os.path.join(task_dir, target_file_rel)
        if os.path.exists(target_abs_path):
            try:
                with open(target_abs_path, 'r') as f:
                    content = f.read()
                # Strip leading 'static ' (but not 'static inline')
                content = re.sub(r'^static\s+(?!inline)', '', content, flags=re.MULTILINE)
                with open(target_abs_path, 'w') as f:
                    f.write(content)
            except Exception as e:
                print(f"Failed to strip static: {e}")

        # 3. Compile
        # Implementation:
        
        # 0. Clean up previous coverage data recursively
        for root, dirs, files in os.walk(task_dir):
            for f in files:
                if f.endswith((".gcda", ".gcno", ".o", ".info")):
                    try:
                        os.remove(os.path.join(root, f))
                    except Exception:
                        pass

        # 1. Compile target with coverage
        # We use -I. and also -I<project_root> and maybe -I<dir_of_target>
        target_dir = os.path.dirname(target_file_rel)
        include_paths = ["-I.", f"-I{task_dir}"]
        if target_dir:
            include_paths.append(f"-I{os.path.join(task_dir, target_dir)}")

        # Add -DUNITY_INCLUDE_DOUBLE to enable double precision assertions
        c_flags = ["-DUNITY_INCLUDE_DOUBLE"]

        cmd_compile_target = ["gcc", "-c", "-fprofile-arcs", "-ftest-coverage"] + c_flags + [target_file_rel] + include_paths
        proc_t = await asyncio.create_subprocess_exec(*cmd_compile_target, cwd=task_dir, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout_t, stderr_t = await proc_t.communicate()
        
        if proc_t.returncode != 0:
             # Save compilation failure to cache
             try:
                 from app.services.cache_service import CacheService
                 if metadata.get("project_id") and metadata.get("source_file_path") and metadata.get("function_name"):
                     CacheService.save_function_data(
                         metadata["project_id"],
                         metadata["source_file_path"],
                         metadata["function_name"],
                         {
                             "latest_task_id": task_id,
                             "last_execution_time": str(datetime.now()),
                             "compile_success": False,
                             "passed": 0,
                             "failed": 0,
                             "ignored": 0,
                             "line_coverage": 0.0,
                             "branch_coverage": 0.0
                         }
                     )
             except Exception:
                 pass

             return ExecuteTestResponse(
                task_id=task_id,
                compile_success=False,
                execution_started=False,
                stderr=f"Target compilation failed:\n{stderr_t.decode(errors='replace')}\n{stdout_t.decode(errors='replace')}"
             )

        # 1b. Weaken all symbols in the target .o EXCEPT the function under test.
        # This is the correct, binary-level solution to "multiple definition" linker
        # errors when the LLM-generated test file redefines a helper from the same .c.
        # Approach:
        #   nm --defined-only -P <file>.o   → lists every symbol defined in the .o
        #   objcopy --weaken-symbol=<sym>   → demotes a symbol to WEAK so the
        #                                     strong definition in the test file wins
        # The target function itself must remain GLOBAL (strong) so gcov can trace it.
        target_obj = os.path.basename(target_file_rel).replace(".c", ".o")
        if function_name:
            try:
                nm_proc = await asyncio.create_subprocess_exec(
                    "nm", "--defined-only", "-P", target_obj,
                    cwd=task_dir,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                nm_out, _ = await nm_proc.communicate()
                # nm -P format: "<name> <type> <value> <size>"
                # We only want TEXT symbols (type T or t) that are NOT the target function
                weaken_args = []
                for line in nm_out.decode(errors='replace').splitlines():
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] in ('T', 't'):
                        sym = parts[0]
                        if sym != function_name:
                            weaken_args.extend([f'--weaken-symbol={sym}'])
                if weaken_args:
                    objcopy_proc = await asyncio.create_subprocess_exec(
                        "objcopy", *weaken_args, target_obj,
                        cwd=task_dir,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                    )
                    await objcopy_proc.communicate()
            except Exception as e:
                print(f"objcopy weaken step failed (non-fatal): {e}")

        # 2. Compile runner & unity
        cmd_compile_others = ["gcc", "-c", "test_runner.c", "unity.c"] + c_flags + include_paths
        proc_o = await asyncio.create_subprocess_exec(*cmd_compile_others, cwd=task_dir, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout_o, stderr_o = await proc_o.communicate()
        
        if proc_o.returncode != 0:
             # Save Runner/Unity compilation failure to cache
             try:
                 from app.services.cache_service import CacheService
                 if metadata.get("project_id") and metadata.get("source_file_path") and metadata.get("function_name"):
                     CacheService.save_function_data(
                         metadata["project_id"],
                         metadata["source_file_path"],
                         metadata["function_name"],
                         {
                             "latest_task_id": task_id,
                             "last_execution_time": str(datetime.now()),
                             "compile_success": False,
                             "passed": 0,
                             "failed": 0,
                             "ignored": 0,
                             "line_coverage": 0.0,
                             "branch_coverage": 0.0
                         }
                     )
             except Exception:
                 pass

             return ExecuteTestResponse(
                task_id=task_id,
                compile_success=False,
                execution_started=False,
                stderr=f"Runner/Unity compilation failed:\n{stderr_o.decode(errors='replace')}\n{stdout_o.decode(errors='replace')}"
             )

        # 3. Link
        # Note: gcc -c klib-master/kstring.c produces kstring.o in current dir
        # Add -lz for zlib support (klib requirement)
        target_obj = os.path.basename(target_file_rel).replace(".c", ".o")
        cmd_link = [
            "gcc", "-o", "runner", 
            "test_runner.o", "unity.o", target_obj, 
            "-lgcov", "--coverage", "-lm", "-lz"
        ]
        
        proc = await asyncio.create_subprocess_exec(
            *cmd_link, 
            cwd=task_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            # Save linking failure to cache
            try:
                from app.services.cache_service import CacheService
                if metadata.get("project_id") and metadata.get("source_file_path") and metadata.get("function_name"):
                    CacheService.save_function_data(
                        metadata["project_id"],
                        metadata["source_file_path"],
                        metadata["function_name"],
                        {
                            "latest_task_id": task_id,
                            "last_execution_time": str(datetime.now()),
                            "compile_success": False,
                             "passed": 0,
                             "failed": 0,
                             "ignored": 0,
                             "line_coverage": 0.0,
                             "branch_coverage": 0.0
                         }
                     )
            except Exception:
                pass

            return ExecuteTestResponse(
                task_id=task_id,
                compile_success=False,
                execution_started=False,
                stderr=f"Linking failed:\n{stderr.decode(errors='replace')}\n{stdout.decode(errors='replace')}"
            )
            
        # 4. Run
        proc_run = await asyncio.create_subprocess_exec(
            "./runner",
            cwd=task_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            run_stdout, run_stderr = await asyncio.wait_for(proc_run.communicate(), timeout=10.0)
        except asyncio.TimeoutError:
            try:
                proc_run.kill()
            except Exception:
                pass
            run_stdout = b""
            run_stderr = b"Execution timed out (10s limit exceeded)."
        
        # 5. Parse Results
        output = run_stdout.decode(errors='replace') + "\n" + run_stderr.decode(errors='replace')
        
        # Check for crash/assertion failure first
        is_crashed = proc_run.returncode != 0
        has_assertion_fail = "Assertion" in output and "failed" in output
        has_segfault = "Segmentation fault" in output
        
        # Official Unity output: "test_runner.c:20:test_add_basic:PASS"
        passed = output.count(":PASS")
        failed = output.count(":FAIL")
        ignored = output.count(":IGNORE")
        
        if proc_run.returncode != 0 and failed == 0:
             # Try to capture more details about the crash
             stderr_msg = run_stderr.decode(errors='replace')
             if not stderr_msg:
                 stderr_msg = f"Process terminated with signal {-proc_run.returncode}" if proc_run.returncode < 0 else f"Process exited with code {proc_run.returncode}"
             
             # Still count as failed
             failed = 1
             
             # Also append to stderr for user visibility
             run_stderr = (run_stderr.decode(errors='replace') + f"\n[System] Test runner crashed: {stderr_msg}").encode()
        
        total = passed + failed + ignored 
        
        # 6. Generate Coverage
        coverage_data = None
        try:
            # Check if .gcda files exist
            # os.listdir(task_dir)
            
            # Use gcov directly to debug/ensure generation
            # gcov source_file
            # The source file we compiled is target_file_name (e.g. sample.c)
            # It was compiled in task_dir.
            # cmd_gcov = ["gcov", target_file_name]
            # proc_gcov = await asyncio.create_subprocess_exec(*cmd_gcov, cwd=task_dir, ...)
            
            # lcov capture
            # lcov --capture --directory . --output-file coverage.info
            # IMPORTANT: we need to run lcov on the directory where gcda files are generated (task_dir)
            
            # 1. Capture all coverage in the task directory
            cmd_lcov = ["lcov", "--capture", "--directory", ".", "--output-file", "all_coverage.info", "--rc", "lcov_branch_coverage=1"]
            proc_lcov = await asyncio.create_subprocess_exec(
                *cmd_lcov,
                cwd=task_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc_lcov.communicate()
            
            # 2. Extract only the target source file to avoid interference from other files
            # target_file_rel is the relative path like 'klib-master/kmath.c'
            cmd_extract = ["lcov", "--extract", "all_coverage.info", f"*/{target_file_rel}", "--output-file", "coverage.info", "--rc", "lcov_branch_coverage=1"]
            proc_extract = await asyncio.create_subprocess_exec(
                *cmd_extract,
                cwd=task_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc_extract.communicate()
            
            # 3. If extraction failed or produced empty file, fall back to all_coverage.info
            info_path = os.path.join(task_dir, "coverage.info")
            if not os.path.exists(info_path) or os.path.getsize(info_path) < 100:
                info_path = os.path.join(task_dir, "all_coverage.info")

            # Parse the finalized coverage.info
            files_cov = RunnerService._parse_lcov_info(info_path, task_dir)
            
            # Sort functions in each file so the target function is first
            target_func_name = metadata.get("function_name")
            
            # If function_name is missing (old task), try to resolve it from function_id
            if not target_func_name and metadata.get("function_id"):
                try:
                    from app.services.parser_service import ParserService
                    import base64
                    parts = metadata["function_id"].rsplit('_', 1)
                    file_id = parts[0]
                    start_line = int(parts[1])
                    path = base64.urlsafe_b64decode(file_id).decode()
                    content = ProjectService.get_file_content(metadata["project_id"], path)
                    functions = ParserService.parse_functions(content, file_id)
                    for f in functions:
                        if f.start_line == start_line:
                            target_func_name = f.name
                            metadata["function_name"] = target_func_name
                            break
                except Exception:
                    pass

            if target_func_name and files_cov:
                for file_cov in files_cov:
                    if file_cov.functions:
                        # Find the target function if it exists in this file
                        target_idx = -1
                        for idx, func in enumerate(file_cov.functions):
                            if func.name == target_func_name:
                                target_idx = idx
                                break
                        
                        if target_idx > 0:
                            # Move it to the front
                            func = file_cov.functions.pop(target_idx)
                            file_cov.functions.insert(0, func)
                        elif target_idx == -1 and len(file_cov.functions) > 0:
                            # If target not found by name, but we have functions, 
                            # maybe it's a naming mismatch (e.g. static prefix removal).
                            # Try to find by line number if we had it, but we don't here easily.
                            # For now, just ensure the most "relevant" looking one is at front.
                            pass
            
            if files_cov:
                coverage_data = TestCoverage(scope="function", files=files_cov)
                
        except Exception as e:
            print(f"Coverage generation failed: {e}")
        
        # Save result
        metadata["result"] = {
            "passed": passed,
            "failed": failed,
            "ignored": ignored,
            "total": total,
            "stdout": output,
            "coverage": coverage_data.model_dump() if coverage_data else None
        }
        with open(os.path.join(task_dir, "metadata.json"), "w") as f:
            json.dump(metadata, f, default=str) # default=str to handle Pydantic/enums if needed

        # Save result to CacheService for persistence
        try:
             from app.services.cache_service import CacheService
             if metadata.get("project_id") and metadata.get("source_file_path") and metadata.get("function_name"):
                 # Extract line rate for the function
                 line_rate = 0.0
                 branch_rate = 0.0
                 if coverage_data and coverage_data.files:
                     # Find the target function coverage
                     for file_cov in coverage_data.files:
                         for func_cov in file_cov.functions:
                             if func_cov.name == metadata["function_name"]:
                                 line_rate = func_cov.line.rate
                                 branch_rate = func_cov.branch.rate
                                 break
                 
                 CacheService.save_function_data(
                     metadata["project_id"],
                     metadata["source_file_path"],
                     metadata["function_name"],
                     {
                         "latest_task_id": task_id,
                         "last_execution_time": str(datetime.now()),
                         "compile_success": True,
                         "passed": passed,
                         "failed": failed,
                         "ignored": ignored,
                         "line_coverage": line_rate,
                         "branch_coverage": branch_rate
                     }
                 )
        except Exception as e:
            print(f"Failed to save execution result to cache: {e}")

        # Read source code content
        source_code_content = None
        target_abs_path = os.path.join(task_dir, target_file_rel)
        if os.path.exists(target_abs_path):
            with open(target_abs_path, 'r') as f:
                source_code_content = f.read()

        # Backfill start_line/end_line if missing (logic copied from get_result)
        start_line = metadata.get("start_line")
        end_line = metadata.get("end_line")
        
        if (start_line is None or end_line is None) and metadata.get("function_id") and source_code_content:
            try:
                from app.services.parser_service import ParserService
                import base64
                parts = metadata["function_id"].rsplit('_', 1)
                file_id = parts[0]
                expected_start = int(parts[1])
                
                functions = ParserService.parse_functions(source_code_content, file_id)
                found = False
                for f in functions:
                    if f.start_line == expected_start:
                        start_line = f.start_line
                        end_line = f.end_line
                        found = True
                        break
                
                if not found and metadata.get("function_name"):
                    for f in functions:
                        if f.name == metadata["function_name"]:
                            start_line = f.start_line
                            end_line = f.end_line
                            found = True
                            break
                
                if found:
                    metadata["start_line"] = start_line
                    metadata["end_line"] = end_line
                    # Update metadata on disk
                    with open(os.path.join(task_dir, "metadata.json"), "w") as f:
                        json.dump(metadata, f, default=str)
            except Exception as e:
                pass

        return ExecuteTestResponse(
            task_id=task_id,
            compile_success=True,
            execution_started=True,
            test_result=TestResultDetail(passed=passed, failed=failed, total=total),
            coverage=coverage_data,
            stdout=output,
            stderr=run_stderr.decode(),
            source_code=source_code_content,
            function_start_line=start_line,
            function_end_line=end_line
        )

    @staticmethod
    def get_result(task_id: str) -> Optional[ExecuteTestResponse]:
        task_dir = os.path.join(TASKS_DIR, task_id)
        meta_path = os.path.join(task_dir, "metadata.json")
        if not os.path.exists(meta_path):
            return None
        with open(meta_path, "r") as f:
            meta = json.load(f)
            
        if "result" not in meta:
             return ExecuteTestResponse(
                task_id=task_id,
                compile_success=True, # Assuming it got this far? 
                execution_started=False
            )
            
        res = meta["result"]
        # Deserialize coverage if exists
        cov_obj = None
        if res.get("coverage"):
            cov_obj = TestCoverage(**res["coverage"])
            
        # Read source code content
        source_code_content = None
        if meta.get("source_file_path"):
            target_abs_path = os.path.join(task_dir, meta["source_file_path"])
            if os.path.exists(target_abs_path):
                with open(target_abs_path, 'r') as f:
                    source_code_content = f.read()

        # If start_line or end_line is missing, try to backfill using ParserService
        start_line = meta.get("start_line")
        end_line = meta.get("end_line")
        
        if (start_line is None or end_line is None) and meta.get("function_id") and source_code_content:
            try:
                from app.services.parser_service import ParserService
                import base64
                parts = meta["function_id"].rsplit('_', 1)
                file_id = parts[0]
                expected_start = int(parts[1])
                
                functions = ParserService.parse_functions(source_code_content, file_id)
                found = False
                # 1. Try to match by start_line
                for f in functions:
                    if f.start_line == expected_start:
                        start_line = f.start_line
                        end_line = f.end_line
                        found = True
                        break
                
                # 2. If not found by line, try by function_name if available
                if not found and meta.get("function_name"):
                    for f in functions:
                        if f.name == meta["function_name"]:
                            start_line = f.start_line
                            end_line = f.end_line
                            found = True
                            break
                
                if found:
                    # Optionally update metadata on disk so we don't parse again
                    meta["start_line"] = start_line
                    meta["end_line"] = end_line
                    try:
                        with open(meta_path, "w") as f_meta:
                            json.dump(meta, f_meta, default=str)
                    except:
                        pass
            except Exception as e:
                pass

        return ExecuteTestResponse(
            task_id=task_id,
            compile_success=True,
            execution_started=True,
            test_result=TestResultDetail(passed=res["passed"], failed=res["failed"], total=res["total"]),
            coverage=cov_obj,
            stdout=res.get("stdout", ""),
            stderr="",
            source_code=source_code_content,
            function_start_line=start_line,
            function_end_line=end_line
        )
