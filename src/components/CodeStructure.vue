<template>
  <div class="structure-panel">
    <div class="header">
      <span class="title">OUTLINE</span>
      <button class="refresh-btn" @click="fetchSymbols" title="Refresh Structure">↻</button>
    </div>
    <div class="content" v-if="symbols.length">
      <div v-for="item in flattenedSymbols" :key="item.id" 
        class="symbol-item" 
        :style="{ paddingLeft: item.indent * 16 + 10 + 'px' }"
        @click="jumpTo(item)"
      >
        <span class="icon" :class="getSymbolClass(item.kind)"></span>
        <span class="name">{{ item.name }}</span>
      </div>
    </div>
    <div class="empty" v-else>
      No symbols found
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, shallowRef } from 'vue'
import * as monaco from 'monaco-editor'

const props = defineProps<{
  editor: monaco.editor.IStandaloneCodeEditor | null
}>()

interface FlatSymbol {
  id: string
  name: string
  kind: monaco.languages.SymbolKind
  range: monaco.IRange
  indent: number
}

const symbols = shallowRef<monaco.languages.DocumentSymbol[]>([])

const flattenedSymbols = computed(() => {
  const result: FlatSymbol[] = []
  
  const traverse = (list: monaco.languages.DocumentSymbol[], indent: number) => {
    for (const sym of list) {
      result.push({
        id: `${sym.name}-${sym.range.startLineNumber}-${sym.range.startColumn}`,
        name: sym.name,
        kind: sym.kind,
        range: sym.range,
        indent
      })
      if (sym.children && sym.children.length) {
        traverse(sym.children, indent + 1)
      }
    }
  }
  
  traverse(symbols.value, 0)
  return result
})

const fetchSymbols = async () => {
  if (!props.editor) return
  const model = props.editor.getModel()
  if (!model) return

  const lang = model.getLanguageId()
  const text = model.getValue()
  const newSymbols: monaco.languages.DocumentSymbol[] = []

  // Try to use JS/TS worker if available
  if (lang === 'typescript' || lang === 'javascript') {
    try {
      // @ts-ignore
      const worker = await monaco.languages.typescript.getTypeScriptWorker()
      const client = await worker(model.uri)
      const items = await client.getNavigationBarItems(model.uri.toString())
      
      // Convert NavigationBarItem to DocumentSymbol
      // This is a simplified conversion
      if (items) {
        // Recursively convert
        const convert = (item: any): monaco.languages.DocumentSymbol => {
           return {
             name: item.text,
             detail: '',
             kind: convertKind(item.kind),
             tags: [],
             range: {
               startLineNumber: 1, // Placeholder, worker returns spans which need source file mapping
               startColumn: 1,
               endLineNumber: 1,
               endColumn: 1
             },
             selectionRange: {
               startLineNumber: 1,
               startColumn: 1,
               endLineNumber: 1,
               endColumn: 1
             },
             children: item.childItems?.map(convert)
           }
        }
        // Actually, getNavigationBarItems returns spans (start, length). 
        // Mapping span to range requires model.getPositionAt(offset).
        // Let's implement the mapping.
        
        const mapSpanToRange = (span: { start: number, length: number }): monaco.IRange => {
          const start = model.getPositionAt(span.start)
          const end = model.getPositionAt(span.start + span.length)
          return {
            startLineNumber: start.lineNumber,
            startColumn: start.column,
            endLineNumber: end.lineNumber,
            endColumn: end.column
          }
        }

        const convertReal = (item: any): monaco.languages.DocumentSymbol => {
          const range = mapSpanToRange(item.spans[0])
          return {
            name: item.text,
            detail: '',
            kind: convertKind(item.kind),
            tags: [],
            range: range,
            selectionRange: range,
            children: item.childItems?.map(convertReal)
          }
        }
        
        symbols.value = items.map(convertReal)
        return
      }
    } catch (e) {
      console.warn('Worker symbol fetch failed, fallback to regex', e)
    }
  }

  // Fallback Regex Parser for other languages or if worker fails
  const lines = text.split('\n')
  
  // Simple regex for classes and functions/methods
  // Matches: class Foo, function bar, def baz, etc.
  const regex = /^\s*(?:class|function|def|interface|const|let|var)\s+([a-zA-Z0-9_]+)/
  
  for (let i = 0; i < lines.length; i++) {
    const match = lines[i].match(regex)
    if (match) {
      const name = match[1]
      // Guess kind
      let kind = monaco.languages.SymbolKind.Variable
      if (lines[i].includes('class')) kind = monaco.languages.SymbolKind.Class
      else if (lines[i].includes('function') || lines[i].includes('def')) kind = monaco.languages.SymbolKind.Function
      else if (lines[i].includes('interface')) kind = monaco.languages.SymbolKind.Interface
      
      newSymbols.push({
        name: name,
        detail: '',
        kind: kind,
        tags: [],
        range: {
          startLineNumber: i + 1,
          startColumn: 1,
          endLineNumber: i + 1,
          endColumn: lines[i].length + 1
        },
        selectionRange: {
          startLineNumber: i + 1,
          startColumn: 1,
          endLineNumber: i + 1,
          endColumn: lines[i].length + 1
        },
        children: []
      })
    }
  }
  
  symbols.value = newSymbols
}

const convertKind = (kind: string): monaco.languages.SymbolKind => {
  // TS worker returns strings like 'class', 'interface', 'method'
  switch (kind) {
    case 'class': return monaco.languages.SymbolKind.Class
    case 'interface': return monaco.languages.SymbolKind.Interface
    case 'method': return monaco.languages.SymbolKind.Method
    case 'function': return monaco.languages.SymbolKind.Function
    case 'var': return monaco.languages.SymbolKind.Variable
    case 'let': return monaco.languages.SymbolKind.Variable
    case 'const': return monaco.languages.SymbolKind.Constant
    case 'module': return monaco.languages.SymbolKind.Module
    default: return monaco.languages.SymbolKind.Property
  }
}

const jumpTo = (item: FlatSymbol) => {
  if (!props.editor) return
  props.editor.revealLineInCenter(item.range.startLineNumber)
  props.editor.setPosition({
    lineNumber: item.range.startLineNumber,
    column: item.range.startColumn
  })
  props.editor.focus()
}

const getSymbolClass = (kind: monaco.languages.SymbolKind) => {
  // Simple mapping for icons (CSS classes)
  // In a real app, use SVG icons
  switch (kind) {
    case monaco.languages.SymbolKind.File: return 'icon-file'
    case monaco.languages.SymbolKind.Module: return 'icon-module'
    case monaco.languages.SymbolKind.Namespace: return 'icon-namespace'
    case monaco.languages.SymbolKind.Package: return 'icon-package'
    case monaco.languages.SymbolKind.Class: return 'icon-class'
    case monaco.languages.SymbolKind.Method: return 'icon-method'
    case monaco.languages.SymbolKind.Property: return 'icon-property'
    case monaco.languages.SymbolKind.Field: return 'icon-field'
    case monaco.languages.SymbolKind.Constructor: return 'icon-constructor'
    case monaco.languages.SymbolKind.Enum: return 'icon-enum'
    case monaco.languages.SymbolKind.Interface: return 'icon-interface'
    case monaco.languages.SymbolKind.Function: return 'icon-function'
    case monaco.languages.SymbolKind.Variable: return 'icon-variable'
    case monaco.languages.SymbolKind.Constant: return 'icon-constant'
    case monaco.languages.SymbolKind.String: return 'icon-string'
    case monaco.languages.SymbolKind.Number: return 'icon-number'
    case monaco.languages.SymbolKind.Boolean: return 'icon-boolean'
    case monaco.languages.SymbolKind.Array: return 'icon-array'
    case monaco.languages.SymbolKind.Object: return 'icon-object'
    case monaco.languages.SymbolKind.Key: return 'icon-key'
    case monaco.languages.SymbolKind.Null: return 'icon-null'
    case monaco.languages.SymbolKind.EnumMember: return 'icon-enum-member'
    case monaco.languages.SymbolKind.Struct: return 'icon-struct'
    case monaco.languages.SymbolKind.Event: return 'icon-event'
    case monaco.languages.SymbolKind.Operator: return 'icon-operator'
    case monaco.languages.SymbolKind.TypeParameter: return 'icon-type-parameter'
    default: return 'icon-default'
  }
}

// Watch editor changes to refresh structure
// Debounce this in real app
let timer: any = null
watch(() => props.editor, (editor) => {
  if (editor) {
    editor.onDidChangeModelContent(() => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(fetchSymbols, 1000)
    })
    // Initial fetch
    setTimeout(fetchSymbols, 500)
  }
})
</script>

<style scoped>
.structure-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #1e1e1e; /* Match VS Dark */
  color: #cccccc;
  border-left: 1px solid #333;
  overflow: hidden;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
}
.header {
  padding: 8px 12px;
  font-size: 11px;
  font-weight: bold;
  text-transform: uppercase;
  background: #252526;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.refresh-btn {
  background: none;
  border: none;
  color: #ccc;
  cursor: pointer;
  font-size: 12px;
}
.refresh-btn:hover {
  color: #fff;
}
.content {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}
.symbol-item {
  display: flex;
  align-items: center;
  padding: 4px 8px;
  cursor: pointer;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.symbol-item:hover {
  background: #2a2d2e;
}
.icon {
  width: 16px;
  height: 16px;
  margin-right: 6px;
  display: inline-block;
  background-size: contain;
  background-repeat: no-repeat;
  background-position: center;
}
/* Basic colors for kinds */
.icon-class { background-color: #ffcc00; mask: url('data:image/svg+xml;utf8,<svg viewBox="0 0 16 16"><path d="..."/></svg>'); } 
/* For demo simplicity, using colored squares or bullets if SVG not available */
.icon::before {
  content: '';
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.icon-class::before { background: #dcdcaa; }
.icon-method::before { background: #dcdcaa; border-radius: 0; }
.icon-function::before { background: #dcdcaa; border-radius: 0; }
.icon-variable::before { background: #9cdcfe; }
.icon-property::before { background: #9cdcfe; }
.empty {
  padding: 20px;
  text-align: center;
  color: #666;
  font-size: 12px;
}
</style>