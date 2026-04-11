import sys
import re

def optimize_pdg_dot(file_path):
    with open(file_path, 'r') as f:
        content = f.read()

    # Check if content is empty or just basic graph header
    if len(content.strip().split('\n')) <= 2:
        return

    # 1. Set horizontal layout
    if 'rankdir=LR' not in content:
        content = content.replace('graph [', 'graph [rankdir=LR, ')
    
    # 2. Add some styles
    style = """
    node [shape=box, style="filled,rounded", fillcolor="#f8fafc", color="#e2e8f0", fontname="Courier", fontsize=10];
    edge [color="#94a3b8", fontname="Courier", fontsize=8, arrowsize=0.7];
    """
    if 'node [' not in content:
        content = content.replace('graph [', 'graph [' + style)

    # 3. Clean up node labels (Joern PDG labels can be long)
    # Example: <operator>.assignment -> =
    content = content.replace('<operator>.assignment', '=')
    content = content.replace('<operator>.addressOf', '&')
    content = content.replace('<operator>.indirectMemberAccess', '->')
    content = content.replace('<operator>.fieldAccess', '.')
    content = content.replace('<operator>.computedMemberAccess', '[]')
    content = content.replace('<operator>.indirection', '*')
    content = content.replace('<operator>.cast', '(cast)')
    
    with open(file_path, 'w') as f:
        f.write(content)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        optimize_pdg_dot(sys.argv[1])
