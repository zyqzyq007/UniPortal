
import asyncio
import httpx
import time

async def verify_stability():
    task_id = "task_8a5bd4ea" # Example task ID
    
    for i in range(3):
        print(f"--- Execution {i+1} ---")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post("http://localhost:8000/api/testcase/execute", json={"task_id": task_id})
        
        if resp.status_code == 200:
            data = resp.json()
            cov = data.get("coverage", {}).get("files", [{}])[0]
            print(f"File: {cov.get('file')}")
            print(f"Lines: {cov.get('line', {}).get('covered')}/{cov.get('line', {}).get('total')}")
            print(f"Branches: {cov.get('branch', {}).get('covered')}/{cov.get('branch', {}).get('total')}")
        else:
            print(f"Error: {resp.text}")
        
        time.sleep(1)

if __name__ == "__main__":
    asyncio.run(verify_stability())
