#!/bin/bash
# generate_callgraph.sh
# 用法: ./generate_callgraph.sh <源码目录> <函数名> <输出目录> [已有CPG路径]

SRC_DIR="$1"
FUNC_NAME="$2"
OUT_DIR="$3"
PRE_CPG="$4"

if [ -z "$SRC_DIR" ] || [ -z "$FUNC_NAME" ] || [ -z "$OUT_DIR" ]; then
    echo "Usage: $0 <source_dir> <function_name> <output_dir> [pre_cpg_path]"
    exit 1
fi

mkdir -p "$OUT_DIR"
PNG_FILE="$OUT_DIR/${FUNC_NAME}_3layer.png"
  DOT_FILE="$OUT_DIR/${FUNC_NAME}_3layer.dot"

# Check if PNG already exists
if [ -f "$PNG_FILE" ]; then
    echo "[*] PNG already exists at $PNG_FILE, skipping..."
    exit 0
fi

# Determine CPG to use
if [ -n "$PRE_CPG" ] && [ -f "$PRE_CPG" ]; then
    CPG_FILE="$PRE_CPG"
    echo "[*] Using provided CPG: $CPG_FILE"
elif [ -f "$SRC_DIR/cpg.bin" ]; then
    CPG_FILE="$SRC_DIR/cpg.bin"
    echo "[*] Found existing CPG in source dir: $CPG_FILE"
else
    CPG_FILE="$OUT_DIR/cpg.bin.zip"
    echo "[*] Generating CPG..."
    /opt/joern/joern-cli/c2cpg.sh -J-Xmx8G "$SRC_DIR" --output "$CPG_FILE"
fi

echo "[*] Creating temporary Joern script..."
TMP_SCRIPT=$(mktemp)
cat > "$TMP_SCRIPT" <<EOL
import java.nio.file._
val funcName = "$FUNC_NAME"
val dotFile = "$DOT_FILE"

// Load CPG
val myCpg = importCpg("$CPG_FILE").get

val startFuncs = myCpg.method.name(funcName).toList
if(startFuncs.isEmpty) {
    println(s"Function not found: \$funcName")
} else {
    val edges = scala.collection.mutable.Set.empty[(String,String)]
    val nodes = scala.collection.mutable.Set.empty[String]

    println(s"[*] Found \${startFuncs.size} starting methods for \$funcName")

    // Traverse Down (Callees - what this function calls)
    def traverseDown(m: io.shiftleft.codepropertygraph.generated.nodes.Method, depth: Int): Unit = {
        if (depth > 3) return
        m.callee.l.filter(c => !c.name.startsWith("<operator>") && c.name != m.name).foreach { c =>
            if (!edges.contains((m.name, c.name))) {
                edges += ((m.name, c.name))
                nodes += c.name
                traverseDown(c, depth + 1)
            }
        }
    }

    // Traverse Up (Callers - who calls this function)
    def traverseUp(m: io.shiftleft.codepropertygraph.generated.nodes.Method, depth: Int): Unit = {
        if (depth > 3) return
        m.caller.l.filter(c => !c.name.startsWith("<operator>") && c.name != m.name).foreach { c =>
            if (!edges.contains((c.name, m.name))) {
                edges += ((c.name, m.name))
                nodes += c.name
                traverseUp(c, depth + 1)
            }
        }
    }

    startFuncs.foreach { m =>
        nodes += m.name
        traverseDown(m, 1)
        traverseUp(m, 1)
    }

    // Generate DOT
    val dot = new StringBuilder
    dot ++= "digraph CallGraph {\nnode [shape=box];\n"
    
    // Highlight all matching start functions
    startFuncs.foreach { m =>
        dot ++= s"""  "\${m.name}" [style=filled, fillcolor=lightblue, color=red, penwidth=3];\n"""
    }
    
    edges.foreach{ case(src,dst) => dot ++= s"""  "\$src" -> "\$dst";\n""" }
    dot ++= "}\n"

    Files.write(Paths.get(dotFile), dot.toString.getBytes)
    println(s"DOT file generated at \$dotFile")
}
EOL

echo "[*] Running Joern to generate DOT..."
# Use a temporary directory for Joern workspace to avoid cluttering the root directory
JOERN_WORK_DIR=$(mktemp -d)
pushd "$JOERN_WORK_DIR" > /dev/null
/opt/joern/joern-cli/joern --script "$TMP_SCRIPT"
popd > /dev/null
rm -rf "$JOERN_WORK_DIR"

if [ ! -f "$DOT_FILE" ]; then
    echo "[!] DOT file not generated. Please check Joern output."
    rm "$TMP_SCRIPT"
    exit 1
fi

echo "[*] Rendering PNG..."
dot -Tpng "$DOT_FILE" -o "$PNG_FILE"

if [ -f "$PNG_FILE" ]; then
    echo "[*] PNG generated at $PNG_FILE"
    # Cleanup DOT file as it is a temporary intermediate file
    if [ -f "$DOT_FILE" ]; then
        rm "$DOT_FILE"
        echo "[*] Removed temporary DOT file"
    fi
else
    echo "[!] PNG generation failed."
fi

rm "$TMP_SCRIPT"
