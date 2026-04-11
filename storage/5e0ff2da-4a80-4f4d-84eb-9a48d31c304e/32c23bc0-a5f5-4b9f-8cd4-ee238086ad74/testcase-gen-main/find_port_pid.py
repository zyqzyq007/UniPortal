import glob
import os
import sys

target_inode = "1251157515"
# Note: The inode from grep might change if the process restarts, but let's try to be generic.
# Actually, better to read /proc/net/tcp dynamically in the script.

def get_pid_port_8000():
    try:
        with open("/proc/net/tcp", "r") as f:
            lines = f.readlines()
        
        inode = None
        for line in lines[1:]: # Skip header
            parts = line.split()
            local_address = parts[1]
            state = parts[3]
            current_inode = parts[9]
            
            # 1F40 is 8000 in hex
            if ":1F40" in local_address and state == "0A": # 0A is LISTEN
                inode = current_inode
                break
        
        if not inode:
            print("No process found listening on port 8000")
            return

        print(f"Found socket inode: {inode}")
        
        # Search /proc for this inode
        for proc_dir in glob.glob("/proc/[0-9]*"):
            try:
                pid = os.path.basename(proc_dir)
                fd_dir = os.path.join(proc_dir, "fd")
                if not os.path.exists(fd_dir):
                    continue
                    
                for fd_link in os.listdir(fd_dir):
                    try:
                        link_path = os.path.join(fd_dir, fd_link)
                        target = os.readlink(link_path)
                        if f"socket:[{inode}]" in target:
                            print(f"Process found: PID={pid}")
                            # Get command line
                            try:
                                with open(os.path.join(proc_dir, "cmdline"), "r") as f:
                                    cmd = f.read().replace('\0', ' ')
                                    print(f"Command: {cmd}")
                            except:
                                pass
                            return
                    except (OSError, IOError):
                        continue
            except (OSError, IOError):
                continue
                
        print("Could not find PID for the socket inode.")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    get_pid_port_8000()
