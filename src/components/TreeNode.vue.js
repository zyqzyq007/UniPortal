/// <reference types="../../node_modules/.vue-global-types/vue_3.5_0_0_0.d.ts" />
import { ref, computed, defineAsyncComponent, watch } from 'vue';
import { getProjectStructure } from '../api/projects';
import { useRoute } from 'vue-router';
defineOptions({ name: 'TreeNode' });
const props = defineProps();
const emit = defineEmits();
const expanded = ref(!!props.expandAll); // Default closed unless expandAll is true
const currentLevel = computed(() => props.level ?? 1);
const loading = ref(false);
const error = ref(false);
const route = useRoute();
const projectId = computed(() => route.params.projectId);
const ArrowIcon = defineAsyncComponent(() => import('../assets/icons/chevron-right.svg'));
const FolderIcon = defineAsyncComponent(() => import('../assets/icons/folder.svg'));
const FolderOpenIcon = defineAsyncComponent(() => import('../assets/icons/folder-open.svg'));
const JsIcon = defineAsyncComponent(() => import('../assets/icons/js.svg'));
const TsIcon = defineAsyncComponent(() => import('../assets/icons/ts.svg'));
const VueIcon = defineAsyncComponent(() => import('../assets/icons/vue.svg'));
const HtmlIcon = defineAsyncComponent(() => import('../assets/icons/html.svg'));
const CssIcon = defineAsyncComponent(() => import('../assets/icons/css.svg'));
const JsonIcon = defineAsyncComponent(() => import('../assets/icons/json.svg'));
const PythonIcon = defineAsyncComponent(() => import('../assets/icons/python.svg'));
const DefaultIcon = defineAsyncComponent(() => import('../assets/icons/default.svg'));
const LoadingIcon = defineAsyncComponent(() => import('../assets/icons/default.svg')); // Placeholder for loading
const currentPath = computed(() => (props.parentPath ? `${props.parentPath}/${props.node.name}` : props.node.name));
const isActive = computed(() => props.activePath === currentPath.value);
const loadChildren = async () => {
    if (loading.value)
        return;
    // If children already loaded and not empty, don't reload
    // Wait, if node.children is undefined, it means we haven't tried loading
    // If node.children is [], it means empty dir or loaded.
    // We can't distinguish empty dir from not loaded if initial is []. 
    // Let's assume initial state from parent sets children to undefined if not loaded?
    // But our backend returns children=[] for dirs.
    // So we need a way to track if we fetched.
    // Let's check if children is empty AND expanded. 
    // Actually, let's just fetch if children is empty? No, empty dir loop.
    // We need a local flag `loaded`
};
const isLoaded = ref(false);
const onClick = async () => {
    if (props.node.type === 'dir') {
        if (currentLevel.value < 5) {
            expanded.value = !expanded.value;
            // Lazy load logic
            if (expanded.value && !isLoaded.value && (!props.node.children || props.node.children.length === 0)) {
                await fetchChildren();
            }
        }
    }
    else {
        emit('open-file', { path: currentPath.value, type: props.node.type });
    }
};
const fetchChildren = async () => {
    try {
        loading.value = true;
        error.value = false;
        const res = await getProjectStructure(projectId.value, currentPath.value);
        if (res.code === 200 && res.data) {
            // The backend returns a root node containing children
            // We need to update props.node.children
            // Since props are readonly, we need to emit an update or mutate if it's an object reference (Vue reactive)
            // FileNode passed from parent is likely reactive.
            props.node.children = res.data.children || [];
            isLoaded.value = true;
        }
    }
    catch (err) {
        console.error('Failed to load children', err);
        error.value = true;
    }
    finally {
        loading.value = false;
    }
};
const childKey = (n) => `${n.type}-${n.name}`;
watch(() => props.expandAll, (val) => {
    if (props.node.type === 'dir') {
        expanded.value = !!val;
        // If expanding all, we might need to load children if not loaded?
        // For recursive expand all, this might trigger mass requests. 
        // Let's limit auto-load on expand-all to avoid flooding, or only expand loaded ones.
        // Or just keep existing behavior (only visual expand).
    }
}, { immediate: true });
const getIcon = (node) => {
    if (loading.value)
        return LoadingIcon; // Or a spinner
    if (node.type === 'dir') {
        return expanded.value ? FolderOpenIcon : FolderIcon;
    }
    const ext = node.name.split('.').pop()?.toLowerCase();
    switch (ext) {
        case 'js': return JsIcon;
        case 'ts': return TsIcon;
        case 'vue': return VueIcon;
        case 'html': return HtmlIcon;
        case 'css': return CssIcon;
        case 'json': return JsonIcon;
        case 'py': return PythonIcon;
        default: return DefaultIcon;
    }
};
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
/** @type {__VLS_StyleScopedClasses['row']} */ ;
/** @type {__VLS_StyleScopedClasses['row']} */ ;
/** @type {__VLS_StyleScopedClasses['arrow']} */ ;
/** @type {__VLS_StyleScopedClasses['name']} */ ;
/** @type {__VLS_StyleScopedClasses['children']} */ ;
/** @type {__VLS_StyleScopedClasses['node']} */ ;
/** @type {__VLS_StyleScopedClasses['node']} */ ;
/** @type {__VLS_StyleScopedClasses['children']} */ ;
/** @type {__VLS_StyleScopedClasses['node']} */ ;
/** @type {__VLS_StyleScopedClasses['row']} */ ;
/** @type {__VLS_StyleScopedClasses['name']} */ ;
/** @type {__VLS_StyleScopedClasses['icon-wrapper']} */ ;
/** @type {__VLS_StyleScopedClasses['children']} */ ;
// CSS variable injection 
// CSS variable injection end 
__VLS_asFunctionalElement(__VLS_intrinsicElements.li, __VLS_intrinsicElements.li)({
    ...{ class: "node" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ onClick: (__VLS_ctx.onClick) },
    ...{ class: "row" },
    ...{ class: ({ active: __VLS_ctx.isActive }) },
});
if (__VLS_ctx.node.type === 'dir') {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ onClick: (__VLS_ctx.onClick) },
        ...{ class: "arrow-wrapper" },
    });
    const __VLS_0 = {}.ArrowIcon;
    /** @type {[typeof __VLS_components.ArrowIcon, ]} */ ;
    // @ts-ignore
    const __VLS_1 = __VLS_asFunctionalComponent(__VLS_0, new __VLS_0({
        ...{ class: "arrow" },
        ...{ class: ({ expanded: __VLS_ctx.expanded }) },
    }));
    const __VLS_2 = __VLS_1({
        ...{ class: "arrow" },
        ...{ class: ({ expanded: __VLS_ctx.expanded }) },
    }, ...__VLS_functionalComponentArgsRest(__VLS_1));
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "icon-wrapper" },
});
const __VLS_4 = ((__VLS_ctx.getIcon(__VLS_ctx.node)));
// @ts-ignore
const __VLS_5 = __VLS_asFunctionalComponent(__VLS_4, new __VLS_4({
    ...{ class: "file-icon" },
}));
const __VLS_6 = __VLS_5({
    ...{ class: "file-icon" },
}, ...__VLS_functionalComponentArgsRest(__VLS_5));
__VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
    ...{ class: (['name', __VLS_ctx.node.type === 'dir' ? 'dir' : 'file']) },
});
(__VLS_ctx.node.name);
if (__VLS_ctx.error) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "error-indicator" },
        title: "加载失败",
    });
}
const __VLS_8 = {}.Transition;
/** @type {[typeof __VLS_components.Transition, typeof __VLS_components.Transition, ]} */ ;
// @ts-ignore
const __VLS_9 = __VLS_asFunctionalComponent(__VLS_8, new __VLS_8({
    name: "collapse",
}));
const __VLS_10 = __VLS_9({
    name: "collapse",
}, ...__VLS_functionalComponentArgsRest(__VLS_9));
__VLS_11.slots.default;
if (__VLS_ctx.node.type === 'dir' && __VLS_ctx.expanded && __VLS_ctx.node.children && __VLS_ctx.node.children.length && __VLS_ctx.currentLevel < 5) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.ul, __VLS_intrinsicElements.ul)({
        ...{ class: "children" },
    });
    for (const [child] of __VLS_getVForSourceType((__VLS_ctx.node.children))) {
        const __VLS_12 = {}.TreeNode;
        /** @type {[typeof __VLS_components.TreeNode, ]} */ ;
        // @ts-ignore
        const __VLS_13 = __VLS_asFunctionalComponent(__VLS_12, new __VLS_12({
            ...{ 'onOpenFile': {} },
            key: (__VLS_ctx.childKey(child)),
            node: (child),
            parentPath: (__VLS_ctx.currentPath),
            activePath: (__VLS_ctx.activePath),
            expandAll: (__VLS_ctx.expandAll),
            level: (__VLS_ctx.currentLevel + 1),
        }));
        const __VLS_14 = __VLS_13({
            ...{ 'onOpenFile': {} },
            key: (__VLS_ctx.childKey(child)),
            node: (child),
            parentPath: (__VLS_ctx.currentPath),
            activePath: (__VLS_ctx.activePath),
            expandAll: (__VLS_ctx.expandAll),
            level: (__VLS_ctx.currentLevel + 1),
        }, ...__VLS_functionalComponentArgsRest(__VLS_13));
        let __VLS_16;
        let __VLS_17;
        let __VLS_18;
        const __VLS_19 = {
            onOpenFile: (...[$event]) => {
                if (!(__VLS_ctx.node.type === 'dir' && __VLS_ctx.expanded && __VLS_ctx.node.children && __VLS_ctx.node.children.length && __VLS_ctx.currentLevel < 5))
                    return;
                __VLS_ctx.$emit('open-file', $event);
            }
        };
        var __VLS_15;
    }
}
var __VLS_11;
/** @type {__VLS_StyleScopedClasses['node']} */ ;
/** @type {__VLS_StyleScopedClasses['row']} */ ;
/** @type {__VLS_StyleScopedClasses['arrow-wrapper']} */ ;
/** @type {__VLS_StyleScopedClasses['arrow']} */ ;
/** @type {__VLS_StyleScopedClasses['icon-wrapper']} */ ;
/** @type {__VLS_StyleScopedClasses['file-icon']} */ ;
/** @type {__VLS_StyleScopedClasses['error-indicator']} */ ;
/** @type {__VLS_StyleScopedClasses['children']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            expanded: expanded,
            currentLevel: currentLevel,
            error: error,
            ArrowIcon: ArrowIcon,
            currentPath: currentPath,
            isActive: isActive,
            onClick: onClick,
            childKey: childKey,
            getIcon: getIcon,
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
