import { ref } from 'vue';
const props = defineProps();
const emit = defineEmits(['select']);
const isOpen = ref(false);
const level = props.level || 0;
const handleClick = () => {
    if (props.node.type === 'directory') {
        isOpen.value = !isOpen.value;
    }
    else {
        emit('select', props.node);
    }
};
const getFileIcon = (filename) => {
    const ext = filename.split('.').pop()?.toLowerCase();
    switch (ext) {
        case 'js': return '📄'; // JS icon
        case 'ts': return '📘'; // TS icon
        case 'vue': return '📗'; // Vue icon
        case 'css': return '🎨';
        case 'html': return '🌐';
        case 'json': return '📋';
        case 'md': return '📝';
        case 'png':
        case 'jpg':
        case 'svg': return '🖼️';
        default: return '📄';
    }
};
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
/** @type {__VLS_StyleScopedClasses['node-content']} */ ;
/** @type {__VLS_StyleScopedClasses['node-content']} */ ;
/** @type {__VLS_StyleScopedClasses['folder-icon']} */ ;
// CSS variable injection 
// CSS variable injection end 
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "file-tree-item" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ onClick: (__VLS_ctx.handleClick) },
    ...{ class: "node-content" },
    ...{ class: ({ 'active': __VLS_ctx.activePath === __VLS_ctx.node.path }) },
    ...{ style: ({ paddingLeft: __VLS_ctx.level * 16 + 12 + 'px' }) },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "icon-wrapper" },
});
if (__VLS_ctx.node.type === 'directory') {
    if (__VLS_ctx.isOpen) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.svg, __VLS_intrinsicElements.svg)({
            width: "14",
            height: "14",
            viewBox: "0 0 24 24",
            fill: "none",
            stroke: "currentColor",
            'stroke-width': "2",
            'stroke-linecap': "round",
            'stroke-linejoin': "round",
            ...{ class: "folder-icon open" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.path, __VLS_intrinsicElements.path)({
            d: "M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z",
        });
    }
    else {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.svg, __VLS_intrinsicElements.svg)({
            width: "14",
            height: "14",
            viewBox: "0 0 24 24",
            fill: "none",
            stroke: "currentColor",
            'stroke-width': "2",
            'stroke-linecap': "round",
            'stroke-linejoin': "round",
            ...{ class: "folder-icon" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.path, __VLS_intrinsicElements.path)({
            d: "M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z",
        });
    }
}
else {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "file-icon" },
    });
    (__VLS_ctx.getFileIcon(__VLS_ctx.node.name));
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
    ...{ class: "node-name" },
});
(__VLS_ctx.node.name);
if (__VLS_ctx.node.type === 'directory' && __VLS_ctx.isOpen) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "children" },
    });
    for (const [child] of __VLS_getVForSourceType((__VLS_ctx.node.children))) {
        const __VLS_0 = {}.FileTreeItem;
        /** @type {[typeof __VLS_components.FileTreeItem, ]} */ ;
        // @ts-ignore
        const __VLS_1 = __VLS_asFunctionalComponent(__VLS_0, new __VLS_0({
            ...{ 'onSelect': {} },
            key: (child.path),
            node: (child),
            level: (__VLS_ctx.level + 1),
            activePath: (__VLS_ctx.activePath),
        }));
        const __VLS_2 = __VLS_1({
            ...{ 'onSelect': {} },
            key: (child.path),
            node: (child),
            level: (__VLS_ctx.level + 1),
            activePath: (__VLS_ctx.activePath),
        }, ...__VLS_functionalComponentArgsRest(__VLS_1));
        let __VLS_4;
        let __VLS_5;
        let __VLS_6;
        const __VLS_7 = {
            onSelect: (...[$event]) => {
                if (!(__VLS_ctx.node.type === 'directory' && __VLS_ctx.isOpen))
                    return;
                __VLS_ctx.$emit('select', $event);
            }
        };
        var __VLS_3;
    }
}
/** @type {__VLS_StyleScopedClasses['file-tree-item']} */ ;
/** @type {__VLS_StyleScopedClasses['node-content']} */ ;
/** @type {__VLS_StyleScopedClasses['icon-wrapper']} */ ;
/** @type {__VLS_StyleScopedClasses['folder-icon']} */ ;
/** @type {__VLS_StyleScopedClasses['open']} */ ;
/** @type {__VLS_StyleScopedClasses['folder-icon']} */ ;
/** @type {__VLS_StyleScopedClasses['file-icon']} */ ;
/** @type {__VLS_StyleScopedClasses['node-name']} */ ;
/** @type {__VLS_StyleScopedClasses['children']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            isOpen: isOpen,
            level: level,
            handleClick: handleClick,
            getFileIcon: getFileIcon,
        };
    },
    emits: {},
    __typeProps: {},
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
    emits: {},
    __typeProps: {},
});
; /* PartiallyEnd: #4569/main.vue */
