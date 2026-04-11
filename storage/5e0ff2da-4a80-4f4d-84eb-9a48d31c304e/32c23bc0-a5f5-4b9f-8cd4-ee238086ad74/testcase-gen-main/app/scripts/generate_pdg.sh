#!/bin/bash

# Usage: ./generate_pdg.sh <project_path> <function_name> <output_dir> [cpg_path]

PROJECT_PATH=$1
FUNCTION_NAME=$2
OUTPUT_DIR=$3
CPG_PATH=$4

if [ -z "$CPG_PATH" ]; then
    CPG_PATH="$PROJECT_PATH/cpg.bin"
fi

JOERN="/opt/joern/joern-cli/joern"
DOT_FILE="$OUTPUT_DIR/${FUNCTION_NAME}_pdg.dot"
PNG_FILE="$OUTPUT_DIR/${FUNCTION_NAME}_pdg.png"
PYTHON_SCRIPT="$(dirname "$0")/optimize_dot.py"

# Create temporary script for Joern
SCRIPT_FILE="/tmp/pdg_$$.sc"
cat <<EOF > "$SCRIPT_FILE"
importCpg("$CPG_PATH")
cpg.method.name("$FUNCTION_NAME").dotPdg.l |> "$DOT_FILE"
EOF

# Run Joern in a temporary directory to avoid workspace pollution
JOERN_WORK_DIR=$(mktemp -d)
pushd "$JOERN_WORK_DIR" > /dev/null
$JOERN --script "$SCRIPT_FILE"
popd > /dev/null
rm -rf "$JOERN_WORK_DIR"

# Optimize DOT and convert to PNG
if [ -f "$DOT_FILE" ]; then
    if [ -f "$PYTHON_SCRIPT" ]; then
        python3 "$PYTHON_SCRIPT" "$DOT_FILE"
    fi
    dot -Tpng "$DOT_FILE" -o "$PNG_FILE"
    rm "$DOT_FILE"
fi

rm "$SCRIPT_FILE"
