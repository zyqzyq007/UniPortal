/// <reference types="../../../node_modules/.vue-global-types/vue_3.5_0_0_0.d.ts" />
import { computed, ref, onMounted, watch } from 'vue';
import { useRoute } from 'vue-router';
import { tools } from '../../mock/data';
const route = useRoute();
const projectId = computed(() => route.params.projectId);
const toolKey = computed(() => route.params.toolKey);
const loading = ref(true);
const targetUrl = computed(() => {
    const tool = tools.find((t) => t.key === toolKey.value);
    return tool?.targetUrl || '';
});
const onLoad = () => {
    loading.value = false;
};
// 监听路由变化，重置加载状态
watch(toolKey, () => {
    loading.value = true;
});
onMounted(() => {
    if (!targetUrl.value) {
        loading.value = false;
    }
});
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
// CSS variable injection 
// CSS variable injection end 
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "tool-viewer" },
});
if (__VLS_ctx.loading) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "loading" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "spinner" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({});
}
if (__VLS_ctx.targetUrl) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.iframe, __VLS_intrinsicElements.iframe)({
        ...{ onLoad: (__VLS_ctx.onLoad) },
        src: (__VLS_ctx.targetUrl),
        ...{ class: "iframe" },
        frameborder: "0",
    });
}
else {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "error" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({});
    const __VLS_0 = {}.RouterLink;
    /** @type {[typeof __VLS_components.RouterLink, typeof __VLS_components.RouterLink, ]} */ ;
    // @ts-ignore
    const __VLS_1 = __VLS_asFunctionalComponent(__VLS_0, new __VLS_0({
        to: (`/projects/${__VLS_ctx.projectId}/tools`),
        ...{ class: "btn" },
    }));
    const __VLS_2 = __VLS_1({
        to: (`/projects/${__VLS_ctx.projectId}/tools`),
        ...{ class: "btn" },
    }, ...__VLS_functionalComponentArgsRest(__VLS_1));
    __VLS_3.slots.default;
    var __VLS_3;
}
/** @type {__VLS_StyleScopedClasses['tool-viewer']} */ ;
/** @type {__VLS_StyleScopedClasses['loading']} */ ;
/** @type {__VLS_StyleScopedClasses['spinner']} */ ;
/** @type {__VLS_StyleScopedClasses['iframe']} */ ;
/** @type {__VLS_StyleScopedClasses['error']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            projectId: projectId,
            loading: loading,
            targetUrl: targetUrl,
            onLoad: onLoad,
        };
    },
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
});
; /* PartiallyEnd: #4569/main.vue */
