/// <reference types="../../../node_modules/.vue-global-types/vue_3.5_0_0_0.d.ts" />
import { computed } from 'vue';
defineOptions({ name: 'SoftwareTreeNode' });
const props = defineProps();
const emit = defineEmits();
const expanded = computed(() => !!props.expandedMap[props.node.path]);
const fileIcon = computed(() => {
    const ext = props.node.name.split('.').pop()?.toLowerCase();
    if (ext === 'js')
        return '🟨';
    if (ext === 'ts')
        return '🔷';
    if (ext === 'json')
        return '🟫';
    if (ext === 'md')
        return '📝';
    return '📄';
});
const escapeReg = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const highlightedName = computed(() => {
    if (!props.keyword.trim())
        return props.node.name;
    const re = new RegExp(`(${escapeReg(props.keyword)})`, 'ig');
    return props.node.name.replace(re, '<mark>$1</mark>');
});
const handleClick = () => {
    if (props.node.type === 'dir') {
        emit('toggle-dir', props.node);
        return;
    }
    emit('open-file', props.node);
};
const toggle = () => {
    if (props.node.type === 'dir') {
        emit('toggle-dir', props.node);
    }
};
const onChildContextmenu = (event, childNode) => {
    emit('contextmenu', event, childNode);
};
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
/** @type {__VLS_StyleScopedClasses['node-row']} */ ;
/** @type {__VLS_StyleScopedClasses['node-row']} */ ;
// CSS variable injection 
// CSS variable injection end 
__VLS_asFunctionalElement(__VLS_intrinsicElements.li, __VLS_intrinsicElements.li)({
    ...{ class: "tree-node" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ onClick: (__VLS_ctx.handleClick) },
    ...{ onContextmenu: (...[$event]) => {
            __VLS_ctx.emit('contextmenu', $event, __VLS_ctx.node);
        } },
    ...{ class: "node-row" },
    ...{ class: ({ active: __VLS_ctx.selectedPath === __VLS_ctx.node.path }) },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
    ...{ onClick: (__VLS_ctx.toggle) },
    ...{ class: "arrow" },
});
if (__VLS_ctx.node.type === 'dir') {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({});
    (__VLS_ctx.expanded ? '▾' : '▸');
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
    ...{ class: "icon" },
});
(__VLS_ctx.node.type === 'dir' ? (__VLS_ctx.expanded ? '📂' : '📁') : __VLS_ctx.fileIcon);
__VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
    ...{ class: "name" },
});
__VLS_asFunctionalDirective(__VLS_directives.vHtml)(null, { ...__VLS_directiveBindingRestFields, value: (__VLS_ctx.highlightedName) }, null, null);
if (__VLS_ctx.node.type === 'dir' && __VLS_ctx.expanded && (__VLS_ctx.node.children || []).length > 0) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.ul, __VLS_intrinsicElements.ul)({
        ...{ class: "children" },
    });
    for (const [child] of __VLS_getVForSourceType((__VLS_ctx.node.children))) {
        const __VLS_0 = {}.SoftwareTreeNode;
        /** @type {[typeof __VLS_components.SoftwareTreeNode, ]} */ ;
        // @ts-ignore
        const __VLS_1 = __VLS_asFunctionalComponent(__VLS_0, new __VLS_0({
            ...{ 'onOpenFile': {} },
            ...{ 'onToggleDir': {} },
            ...{ 'onContextmenu': {} },
            key: (child.path),
            node: (child),
            selectedPath: (__VLS_ctx.selectedPath),
            expandedMap: (__VLS_ctx.expandedMap),
            keyword: (__VLS_ctx.keyword),
        }));
        const __VLS_2 = __VLS_1({
            ...{ 'onOpenFile': {} },
            ...{ 'onToggleDir': {} },
            ...{ 'onContextmenu': {} },
            key: (child.path),
            node: (child),
            selectedPath: (__VLS_ctx.selectedPath),
            expandedMap: (__VLS_ctx.expandedMap),
            keyword: (__VLS_ctx.keyword),
        }, ...__VLS_functionalComponentArgsRest(__VLS_1));
        let __VLS_4;
        let __VLS_5;
        let __VLS_6;
        const __VLS_7 = {
            onOpenFile: (...[$event]) => {
                if (!(__VLS_ctx.node.type === 'dir' && __VLS_ctx.expanded && (__VLS_ctx.node.children || []).length > 0))
                    return;
                __VLS_ctx.emit('open-file', $event);
            }
        };
        const __VLS_8 = {
            onToggleDir: (...[$event]) => {
                if (!(__VLS_ctx.node.type === 'dir' && __VLS_ctx.expanded && (__VLS_ctx.node.children || []).length > 0))
                    return;
                __VLS_ctx.emit('toggle-dir', $event);
            }
        };
        const __VLS_9 = {
            onContextmenu: (__VLS_ctx.onChildContextmenu)
        };
        var __VLS_3;
    }
}
/** @type {__VLS_StyleScopedClasses['tree-node']} */ ;
/** @type {__VLS_StyleScopedClasses['node-row']} */ ;
/** @type {__VLS_StyleScopedClasses['arrow']} */ ;
/** @type {__VLS_StyleScopedClasses['icon']} */ ;
/** @type {__VLS_StyleScopedClasses['name']} */ ;
/** @type {__VLS_StyleScopedClasses['children']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            emit: emit,
            expanded: expanded,
            fileIcon: fileIcon,
            highlightedName: highlightedName,
            handleClick: handleClick,
            toggle: toggle,
            onChildContextmenu: onChildContextmenu,
        };
    },
    __typeEmits: {},
    __typeProps: {},
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
    __typeEmits: {},
    __typeProps: {},
});
; /* PartiallyEnd: #4569/main.vue */
