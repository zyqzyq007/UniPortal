import os
import subprocess
import json
import asyncio
import shutil
import tempfile
from typing import List, Dict, Any, Optional, Tuple

class JoernService:
    JOERN_PARSE = "/opt/joern/joern-cli/joern-parse"
    JOERN_QUERY = "/opt/joern/joern-cli/joern"
    
    @staticmethod
    def _get_env() -> Dict[str, str]:
        """
        Returns a copy of os.environ with JAVA_HOME updated if JOERN_JAVA_HOME is set.
        """
        env = os.environ.copy()
        joern_java_home = os.environ.get("JOERN_JAVA_HOME")
        if joern_java_home:
            env["JAVA_HOME"] = joern_java_home
            # Prepend to PATH to ensure this java is used
            env["PATH"] = f"{os.path.join(joern_java_home, 'bin')}:{env.get('PATH', '')}"
        return env

    @staticmethod
    async def _exec_in_temp_cwd(cmd: List[str]) -> Tuple[int, bytes, bytes]:
        """
        Executes a command in a temporary directory to prevent Joern from polluting the root
        with 'workspace' folders.
        """
        temp_dir = tempfile.mkdtemp()
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=JoernService._get_env(),
                cwd=temp_dir
            )
            stdout, stderr = await process.communicate()
            return process.returncode, stdout, stderr
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    @staticmethod
    async def parse_project(project_path: str, cpg_path: str) -> bool:
        """
        Runs joern-parse on the project directory.
        """
        if os.path.exists(cpg_path):
            return True
            
        cmd = [JoernService.JOERN_PARSE, project_path, "--output", cpg_path]
        try:
            returncode, stdout, stderr = await JoernService._exec_in_temp_cwd(cmd)
            
            if returncode == 0:
                return True
            else:
                err_msg = stderr.decode()
                if "UnsupportedClassVersionError" in err_msg or "class file version 61.0" in err_msg:
                    print("Warning: Joern requires Java 17+, but current environment has an older version. Switching to Regex fallback mode.")
                else:
                    print(f"Joern parse failed: {err_msg}")
                return False
        except Exception as e:
            print(f"Error running joern-parse: {e}")
            return False

    @staticmethod
    async def query_cpg(cpg_path: str, query: str) -> Optional[str]:
        """
        Runs a joern query against a CPG.
        """
        if not os.path.exists(cpg_path):
            return None
            
        script = f"""
        val myCpg = importCpg("{cpg_path}").get
        println({query})
        """
        script_path = f"/tmp/joern_query_direct_{os.getpid()}.sc"
        with open(script_path, "w") as f:
            f.write(script)
            
        cmd = [JoernService.JOERN_QUERY, "--script", script_path]
        try:
            returncode, stdout, stderr = await JoernService._exec_in_temp_cwd(cmd)
            
            if returncode == 0:
                return stdout.decode()
            else:
                print(f"Joern query failed: {stderr.decode()}")
                return None
        finally:
            if os.path.exists(script_path):
                os.remove(script_path)

    @staticmethod
    async def generate_graph_image(project_path: str, function_name: str, refresh: bool = False) -> Optional[str]:
        """
        Runs generate_callgraph.sh to create a PNG representation of the call graph.
        Returns the path to the generated PNG file relative to project_path.
        """
        script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "generate_callgraph.sh")
        return await JoernService._run_graph_script(script_path, project_path, function_name, f"{function_name}_3layer.png", refresh)

    @staticmethod
    async def generate_ast_image(project_path: str, function_name: str, refresh: bool = False) -> Optional[str]:
        script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "generate_ast.sh")
        return await JoernService._run_graph_script(script_path, project_path, function_name, f"{function_name}_ast.png", refresh)

    @staticmethod
    async def generate_cfg_image(project_path: str, function_name: str, refresh: bool = False) -> Optional[str]:
        script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "generate_cfg.sh")
        return await JoernService._run_graph_script(script_path, project_path, function_name, f"{function_name}_cfg.png", refresh)

    @staticmethod
    async def generate_pdg_image(project_path: str, function_name: str, refresh: bool = False) -> Optional[str]:
        script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "generate_pdg.sh")
        return await JoernService._run_graph_script(script_path, project_path, function_name, f"{function_name}_pdg.png", refresh)

    @staticmethod
    async def _run_graph_script(script_path: str, project_path: str, function_name: str, png_filename: str, refresh: bool = False) -> Optional[str]:
        output_dir = os.path.join(project_path, "graphs")
        os.makedirs(output_dir, exist_ok=True)
        png_path = os.path.join(output_dir, png_filename)
        
        if not refresh and os.path.exists(png_path):
            return png_filename
            
        cpg_path = os.path.join(project_path, "cpg.bin")
        cmd = ["bash", script_path, project_path, function_name, output_dir]
        if os.path.exists(cpg_path):
            cmd.append(cpg_path)
        
        try:
            returncode, stdout, stderr = await JoernService._exec_in_temp_cwd(cmd)
            
            if os.path.exists(png_path):
                return png_filename
            else:
                print(f"Joern graph generation failed for {png_filename}: {stderr.decode()}")
                return None
        except Exception as e:
            print(f"Error running graph script {script_path}: {e}")
            return None

    @staticmethod
    async def get_function_cpg_depth(cpg_path: str, function_name: str, depth: int = 3, refresh: bool = False) -> Dict[str, Any]:
        """
        Extracts call graph and data flow for a function up to a certain depth.
        Results are cached in a JSON file to avoid repeated JVM startup.
        """
        project_dir = os.path.dirname(cpg_path)
        cache_dir = os.path.join(project_dir, "graphs")
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, f"{function_name}_data.json")
        
        # 1. Check cache
        if not refresh and os.path.exists(cache_file):
            try:
                with open(cache_file, "r") as f:
                    return json.load(f)
            except:
                pass

        # 2. Run Joern
        script = f"""
        import io.shiftleft.codepropertygraph.generated.nodes
        import io.shiftleft.semanticcpg.language._
        
        // Load CPG inside the script to avoid --cpg option issues
        val myCpg = importCpg("{cpg_path}").get
        
        val func = myCpg.method.name("{function_name}").headOption
        if (func.isDefined) {{
            val m = func.get
            
            // Get calls (1st level for now to ensure stability)
            val calls = m.callOut.map(c => Map(
                "name" -> c.name,
                "signature" -> c.signature,
                "file" -> c.file.name.headOption.getOrElse(""),
                "line" -> c.lineNumber.headOption.getOrElse(0).toString
            )).l.distinct

            val vars = (m.local.name.l ++ m.parameter.name.l).distinct
            val returns = m.methodReturn.toReturn.code.l.distinct
            
            println("---JSON_START---")
            // Manually construct JSON to avoid upickle/asJson dependency issues with complex types
            val vJson = vars.map(v => "\\"" + v + "\\"").mkString("[", ",", "]")
            val rJson = returns.map(r => "\\"" + r.replace("\\"", "\\\\\\"") + "\\"").mkString("[", ",", "]")
            val cJson = calls.map(c => {{
                val name = c.getOrElse("name", "")
                val sig = c.getOrElse("signature", "")
                val file = c.getOrElse("file", "")
                val line = c.getOrElse("line", "0")
                s"{{\\"name\\":\\"$name\\",\\"signature\\":\\"$sig\\",\\"file\\":\\"$file\\",\\"line\\":$line}}"
            }}).mkString("[", ",", "]")
            
            println(s"{{\\"variables\\": $vJson, \\"calls\\": $cJson, \\"returns\\": $rJson}}")
            println("---JSON_END---")
        }} else {{
            println("---JSON_START---")
            println("{{}}")
            println("---JSON_END---")
        }}
        """
        
        script_path = f"/tmp/joern_query_{os.getpid()}.sc"
        with open(script_path, "w") as f:
            f.write(script)
            
        cmd = [JoernService.JOERN_QUERY, "--script", script_path]
        try:
            returncode, stdout, stderr = await JoernService._exec_in_temp_cwd(cmd)
            
            if returncode == 0:
                output = stdout.decode()
                # Use markers to find the JSON part
                try:
                    if "---JSON_START---" in output:
                        json_part = output.split("---JSON_START---")[1].split("---JSON_END---")[0].strip()
                        data = json.loads(json_part)
                        # Save to cache
                        if data:
                            with open(cache_file, "w") as f:
                                json.dump(data, f)
                        return data
                except Exception as e:
                    print(f"Failed to parse Joern JSON: {e}")
            else:
                print(f"Joern script execution failed: {stderr.decode()}")
            return {}
        finally:
            if os.path.exists(script_path):
                os.remove(script_path)
