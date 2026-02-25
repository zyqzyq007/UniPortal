/// <reference types="../../node_modules/.vue-global-types/vue_3.5_0_0_0.d.ts" />
import { computed, watch, shallowRef } from 'vue';
import * as monaco from 'monaco-editor';
const props = defineProps();
const symbols = shallowRef([]);
const flattenedSymbols = computed(() => {
    const result = [];
    const traverse = (list, indent) => {
        for (const sym of list) {
            result.push({
                id: `${sym.name}-${sym.range.startLineNumber}-${sym.range.startColumn}`,
                name: sym.name,
                kind: sym.kind,
                range: sym.range,
                indent
            });
            if (sym.children && sym.children.length) {
                traverse(sym.children, indent + 1);
            }
        }
    };
    traverse(symbols.value, 0);
    return result;
});
const fetchSymbols = async () => {
    if (!props.editor)
        return;
    const model = props.editor.getModel();
    if (!model)
        return;
    const lang = model.getLanguageId();
    const text = model.getValue();
    const newSymbols = [];
    // Try to use JS/TS worker if available
    if (lang === 'typescript' || lang === 'javascript') {
        try {
            // @ts-ignore
            const worker = await monaco.languages.typescript.getTypeScriptWorker();
            const client = await worker(model.uri);
            const items = await client.getNavigationBarItems(model.uri.toString());
            // Convert NavigationBarItem to DocumentSymbol
            // This is a simplified conversion
            if (items) {
                // Recursively convert
                const convert = (item) => {
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
                    };
                };
                // Actually, getNavigationBarItems returns spans (start, length). 
                // Mapping span to range requires model.getPositionAt(offset).
                // Let's implement the mapping.
                const mapSpanToRange = (span) => {
                    const start = model.getPositionAt(span.start);
                    const end = model.getPositionAt(span.start + span.length);
                    return {
                        startLineNumber: start.lineNumber,
                        startColumn: start.column,
                        endLineNumber: end.lineNumber,
                        endColumn: end.column
                    };
                };
                const convertReal = (item) => {
                    const range = mapSpanToRange(item.spans[0]);
                    return {
                        name: item.text,
                        detail: '',
                        kind: convertKind(item.kind),
                        tags: [],
                        range: range,
                        selectionRange: range,
                        children: item.childItems?.map(convertReal)
                    };
                };
                symbols.value = items.map(convertReal);
                return;
            }
        }
        catch (e) {
            console.warn('Worker symbol fetch failed, fallback to regex', e);
        }
    }
    // Fallback Regex Parser for other languages or if worker fails
    const lines = text.split('\n');
    // Simple regex for classes and functions/methods
    // Matches: class Foo, function bar, def baz, etc.
    const regex = /^\s*(?:class|function|def|interface|const|let|var)\s+([a-zA-Z0-9_]+)/;
    for (let i = 0; i < lines.length; i++) {
        const match = lines[i].match(regex);
        if (match) {
            const name = match[1];
            // Guess kind
            let kind = monaco.languages.SymbolKind.Variable;
            if (lines[i].includes('class'))
                kind = monaco.languages.SymbolKind.Class;
            else if (lines[i].includes('function') || lines[i].includes('def'))
                kind = monaco.languages.SymbolKind.Function;
            else if (lines[i].includes('interface'))
                kind = monaco.languages.SymbolKind.Interface;
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
            });
        }
    }
    symbols.value = newSymbols;
};
const convertKind = (kind) => {
    // TS worker returns strings like 'class', 'interface', 'method'
    switch (kind) {
        case 'class': return monaco.languages.SymbolKind.Class;
        case 'interface': return monaco.languages.SymbolKind.Interface;
        case 'method': return monaco.languages.SymbolKind.Method;
        case 'function': return monaco.languages.SymbolKind.Function;
        case 'var': return monaco.languages.SymbolKind.Variable;
        case 'let': return monaco.languages.SymbolKind.Variable;
        case 'const': return monaco.languages.SymbolKind.Constant;
        case 'module': return monaco.languages.SymbolKind.Module;
        default: return monaco.languages.SymbolKind.Property;
    }
};
const jumpTo = (item) => {
    if (!props.editor)
        return;
    props.editor.revealLineInCenter(item.range.startLineNumber);
    props.editor.setPosition({
        lineNumber: item.range.startLineNumber,
        column: item.range.startColumn
    });
    props.editor.focus();
};
const getSymbolClass = (kind) => {
    // Simple mapping for icons (CSS classes)
    // In a real app, use SVG icons
    switch (kind) {
        case monaco.languages.SymbolKind.File: return 'icon-file';
        case monaco.languages.SymbolKind.Module: return 'icon-module';
        case monaco.languages.SymbolKind.Namespace: return 'icon-namespace';
        case monaco.languages.SymbolKind.Package: return 'icon-package';
        case monaco.languages.SymbolKind.Class: return 'icon-class';
        case monaco.languages.SymbolKind.Method: return 'icon-method';
        case monaco.languages.SymbolKind.Property: return 'icon-property';
        case monaco.languages.SymbolKind.Field: return 'icon-field';
        case monaco.languages.SymbolKind.Constructor: return 'icon-constructor';
        case monaco.languages.SymbolKind.Enum: return 'icon-enum';
        case monaco.languages.SymbolKind.Interface: return 'icon-interface';
        case monaco.languages.SymbolKind.Function: return 'icon-function';
        case monaco.languages.SymbolKind.Variable: return 'icon-variable';
        case monaco.languages.SymbolKind.Constant: return 'icon-constant';
        case monaco.languages.SymbolKind.String: return 'icon-string';
        case monaco.languages.SymbolKind.Number: return 'icon-number';
        case monaco.languages.SymbolKind.Boolean: return 'icon-boolean';
        case monaco.languages.SymbolKind.Array: return 'icon-array';
        case monaco.languages.SymbolKind.Object: return 'icon-object';
        case monaco.languages.SymbolKind.Key: return 'icon-key';
        case monaco.languages.SymbolKind.Null: return 'icon-null';
        case monaco.languages.SymbolKind.EnumMember: return 'icon-enum-member';
        case monaco.languages.SymbolKind.Struct: return 'icon-struct';
        case monaco.languages.SymbolKind.Event: return 'icon-event';
        case monaco.languages.SymbolKind.Operator: return 'icon-operator';
        case monaco.languages.SymbolKind.TypeParameter: return 'icon-type-parameter';
        default: return 'icon-default';
    }
};
// Watch editor changes to refresh structure
// Debounce this in real app
let timer = null;
watch(() => props.editor, (editor) => {
    if (editor) {
        editor.onDidChangeModelContent(() => {
            if (timer)
                clearTimeout(timer);
            timer = setTimeout(fetchSymbols, 1000);
        });
        // Initial fetch
        setTimeout(fetchSymbols, 500);
    }
});
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
/** @type {__VLS_StyleScopedClasses['refresh-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['symbol-item']} */ ;
/** @type {__VLS_StyleScopedClasses['icon']} */ ;
/** @type {__VLS_StyleScopedClasses['icon-class']} */ ;
// CSS variable injection 
// CSS variable injection end 
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "structure-panel" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "header" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
    ...{ class: "title" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
    ...{ onClick: (__VLS_ctx.fetchSymbols) },
    ...{ class: "refresh-btn" },
    title: "Refresh Structure",
});
if (__VLS_ctx.symbols.length) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "content" },
    });
    for (const [item] of __VLS_getVForSourceType((__VLS_ctx.flattenedSymbols))) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ onClick: (...[$event]) => {
                    if (!(__VLS_ctx.symbols.length))
                        return;
                    __VLS_ctx.jumpTo(item);
                } },
            key: (item.id),
            ...{ class: "symbol-item" },
            ...{ style: ({ paddingLeft: item.indent * 16 + 10 + 'px' }) },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
            ...{ class: "icon" },
            ...{ class: (__VLS_ctx.getSymbolClass(item.kind)) },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
            ...{ class: "name" },
        });
        (item.name);
    }
}
else {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "empty" },
    });
}
/** @type {__VLS_StyleScopedClasses['structure-panel']} */ ;
/** @type {__VLS_StyleScopedClasses['header']} */ ;
/** @type {__VLS_StyleScopedClasses['title']} */ ;
/** @type {__VLS_StyleScopedClasses['refresh-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['content']} */ ;
/** @type {__VLS_StyleScopedClasses['symbol-item']} */ ;
/** @type {__VLS_StyleScopedClasses['icon']} */ ;
/** @type {__VLS_StyleScopedClasses['name']} */ ;
/** @type {__VLS_StyleScopedClasses['empty']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            symbols: symbols,
            flattenedSymbols: flattenedSymbols,
            fetchSymbols: fetchSymbols,
            jumpTo: jumpTo,
            getSymbolClass: getSymbolClass,
        };
    },
    __typeProps: {},
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
    __typeProps: {},
});
; /* PartiallyEnd: #4569/main.vue */
