import time
import httpx
import uvicorn
import threading
import os
import sys
import base64
from app.main import app

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error")

def verify():
    # Start server
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(2) # Wait for server
    
    base_url = "http://127.0.0.1:8000"
    client = httpx.Client(timeout=30)
    
    try:
        print("1. Uploading project...")
        files = {'file': ('sample.c', open('sample.c', 'rb'), 'text/plain')}
        res = client.post(f"{base_url}/api/project/upload", files=files)
        if res.status_code != 200:
            print(f"Upload failed: {res.text}")
            return
        project_data = res.json()
        project_id = project_data["project_id"]
        print(f"   Project uploaded: {project_id}")
        
        print("2. Getting structure...")
        res = client.get(f"{base_url}/api/project/{project_id}/structure")
        structure = res.json()
        files = structure["files"]
        if not files:
            print("   No files found in structure")
            return
        
        target_file = files[0]
        functions = target_file["functions"]
        print(f"   Found {len(functions)} functions")
        
        target_func = next((f for f in functions if f["name"] == "add"), None)
        if not target_func:
            print("   Function 'add' not found")
            return
        
        function_id = target_func["function_id"]
        print(f"   Target function: {target_func['name']} (ID: {function_id})")
        
        print("3. Getting function detail...")
        res = client.get(f"{base_url}/api/project/{project_id}/function/{function_id}")
        func_detail = res.json()
        print(f"   Code Graph: {func_detail['code_graph']}")
        
        print("4. Generating test case...")
        payload = {
            "project_id": project_id,
            "function_id": function_id,
            "test_framework": "unity"
        }
        res = client.post(f"{base_url}/api/testcase/generate", json=payload)
        if res.status_code != 200:
            print(f"Generate failed: {res.text}")
            return
        gen_data = res.json()
        task_id = gen_data["task_id"]
        print(f"   Task created: {task_id}")
        print(f"   Generated Code Preview:\n{gen_data['test_code'][:100]}...")
        
        print("5. Executing test case...")
        payload = {"task_id": task_id}
        res = client.post(f"{base_url}/api/testcase/execute", json=payload)
        if res.status_code != 200:
            print(f"Execute failed: {res.text}")
            return
        exec_data = res.json()
        print(f"   Compile Success: {exec_data['compile_success']}")
        if exec_data['test_result']:
            print(f"   Result: {exec_data['test_result']}")
        if exec_data.get('coverage'):
            print(f"   Coverage: {exec_data['coverage']}")
        else:
            print(f"   Result not available immediately. Stderr: {exec_data.get('stderr')}")

        if exec_data['compile_success']:
            print("SUCCESS: Full flow verified!")
        else:
            print("FAILURE: Compilation failed.")
            
    except Exception as e:
        print(f"Verification failed with exception: {e}")
    finally:
        pass

if __name__ == "__main__":
    verify()
