/// <reference types="../../node_modules/.vue-global-types/vue_3.5_0_0_0.d.ts" />
import { computed, ref, watch } from 'vue';
import TreeNode from './TreeNode.vue';
const props = defineProps();
const __VLS_emit = defineEmits();
const query = ref('');
const expandAll = ref(false);
const toggleAll = () => {
    expandAll.value = !expandAll.value;
};
const filterNodes = (list, q) => {
    if (!q)
        return list;
    const low = q.toLowerCase();
    const walk = (n) => {
        const nameMatch = n.name.toLowerCase().includes(low);
        // If it's a directory, check children
        // But children might not be loaded yet for lazy load.
        // If we want search to work on lazy loaded structure, we can only search loaded nodes.
        // Backend search is not implemented, so we filter what we have.
        if (n.type === 'dir') {
            const children = n.children || [];
            const kids = children.map(walk).filter(Boolean);
            if (nameMatch || kids.length)
                return { ...n, children: kids };
            return null;
        }
        return nameMatch ? n : null;
    };
    return list.map(walk).filter(Boolean);
};
const filtered = computed(() => filterNodes(props.nodes, query.value));
watch(() => query.value, (q) => {
    if (q)
        expandAll.value = true;
});
const nodeKey = (n) => `${n.type}-${n.name}`;
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
/** @type {__VLS_StyleScopedClasses['btn-toggle']} */ ;
/** @type {__VLS_StyleScopedClasses['tree-toolbar']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-toggle']} */ ;
/** @type {__VLS_StyleScopedClasses['row']} */ ;
/** @type {__VLS_StyleScopedClasses['icon']} */ ;
/** @type {__VLS_StyleScopedClasses['icon']} */ ;
// CSS variable injection 
// CSS variable injection end 
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "tree-wrap" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "tree-toolbar" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.input)({
    ...{ class: "search" },
    placeholder: "搜索文件或文件夹",
});
(__VLS_ctx.query);
__VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
    ...{ onClick: (__VLS_ctx.toggleAll) },
    ...{ class: "btn-toggle" },
});
(__VLS_ctx.expandAll ? '全部收起' : '全部展开');
__VLS_asFunctionalElement(__VLS_intrinsicElements.ul, __VLS_intrinsicElements.ul)({
    ...{ class: "tree" },
});
for (const [node] of __VLS_getVForSourceType((__VLS_ctx.filtered))) {
    /** @type {[typeof TreeNode, ]} */ ;
    // @ts-ignore
    const __VLS_0 = __VLS_asFunctionalComponent(TreeNode, new TreeNode({
        ...{ 'onOpenFile': {} },
        key: (__VLS_ctx.nodeKey(node)),
        node: (node),
        activePath: (__VLS_ctx.activePath),
        expandAll: (__VLS_ctx.expandAll),
        level: (1),
    }));
    const __VLS_1 = __VLS_0({
        ...{ 'onOpenFile': {} },
        key: (__VLS_ctx.nodeKey(node)),
        node: (node),
        activePath: (__VLS_ctx.activePath),
        expandAll: (__VLS_ctx.expandAll),
        level: (1),
    }, ...__VLS_functionalComponentArgsRest(__VLS_0));
    let __VLS_3;
    let __VLS_4;
    let __VLS_5;
    const __VLS_6 = {
        onOpenFile: (...[$event]) => {
            __VLS_ctx.$emit('open-file', $event);
        }
    };
    var __VLS_2;
}
/** @type {__VLS_StyleScopedClasses['tree-wrap']} */ ;
/** @type {__VLS_StyleScopedClasses['tree-toolbar']} */ ;
/** @type {__VLS_StyleScopedClasses['search']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-toggle']} */ ;
/** @type {__VLS_StyleScopedClasses['tree']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            TreeNode: TreeNode,
            query: query,
            expandAll: expandAll,
            toggleAll: toggleAll,
            filtered: filtered,
            nodeKey: nodeKey,
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
