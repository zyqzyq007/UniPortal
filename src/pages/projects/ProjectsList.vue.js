/// <reference types="../../../node_modules/.vue-global-types/vue_3.5_0_0_0.d.ts" />
import { onMounted, ref, computed } from 'vue';
import { useRouter } from 'vue-router';
import { getProjects, deleteProject } from '../../api/projects';
const router = useRouter();
const projects = ref([]);
const loading = ref(true);
const activeCardId = ref(null);
// 删除相关状态
const showDeleteModal = ref(false);
const projectToDelete = ref(null);
const isDeleting = ref(false);
// 双击检测状态
let lastClickTime = 0;
let lastClickId = '';
let clickTimeout = null;
// 检查是否应该显示返回按钮
const showBackButton = computed(() => {
    const state = window.history.state;
    const back = state?.back;
    // 如果没有历史记录，或者上一页是登录页，则不显示返回按钮
    return back && typeof back === 'string' && !back.includes('/login');
});
const fetchProjects = async () => {
    try {
        loading.value = true;
        const res = await getProjects();
        projects.value = res.data;
    }
    catch (error) {
        console.error('Failed to fetch projects', error);
    }
    finally {
        loading.value = false;
    }
};
onMounted(() => {
    fetchProjects();
});
const goBack = () => {
    router.back();
};
const confirmDelete = (project) => {
    projectToDelete.value = project;
    showDeleteModal.value = true;
};
const cancelDelete = () => {
    showDeleteModal.value = false;
    projectToDelete.value = null;
};
const handleDelete = async () => {
    if (!projectToDelete.value)
        return;
    console.log('Deleting project:', projectToDelete.value);
    try {
        isDeleting.value = true;
        await deleteProject(projectToDelete.value.project_id);
        console.log('Delete success');
        // 从列表中移除
        projects.value = projects.value.filter(p => p.project_id !== projectToDelete.value?.project_id);
        showDeleteModal.value = false;
        projectToDelete.value = null;
    }
    catch (error) {
        console.error('Delete failed', error);
        if (error.code === 404) {
            alert('项目不存在或已被删除，将从列表中移除');
            projects.value = projects.value.filter(p => p.project_id !== projectToDelete.value?.project_id);
            showDeleteModal.value = false;
            projectToDelete.value = null;
        }
        else {
            alert('删除失败，请重试');
        }
    }
    finally {
        isDeleting.value = false;
    }
};
const handleCardClick = (id) => {
    const now = Date.now();
    // 触发视觉反馈
    activeCardId.value = id;
    setTimeout(() => {
        activeCardId.value = null;
    }, 200);
    // 双击逻辑：同一ID且时间间隔小于300ms
    if (id === lastClickId && now - lastClickTime < 300) {
        if (clickTimeout)
            clearTimeout(clickTimeout);
        // 双击触发
        router.push(`/projects/${id}`);
        lastClickId = '';
        lastClickTime = 0;
    }
    else {
        // 单击
        lastClickId = id;
        lastClickTime = now;
        // 重置点击状态（防抖/防止误判）
        if (clickTimeout)
            clearTimeout(clickTimeout);
        clickTimeout = setTimeout(() => {
            lastClickId = '';
            lastClickTime = 0;
        }, 300);
    }
};
// 移动端触摸支持优化
const handleTouchStart = (id) => {
    // 可以在这里添加额外的触摸逻辑，目前复用点击逻辑即可
    // 这里的touchstart主要用于更快的响应视觉反馈
    activeCardId.value = id;
};
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
/** @type {__VLS_StyleScopedClasses['btn-back']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-back']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-primary']} */ ;
/** @type {__VLS_StyleScopedClasses['card']} */ ;
/** @type {__VLS_StyleScopedClasses['card']} */ ;
/** @type {__VLS_StyleScopedClasses['card']} */ ;
/** @type {__VLS_StyleScopedClasses['card']} */ ;
/** @type {__VLS_StyleScopedClasses['card']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-enter']} */ ;
/** @type {__VLS_StyleScopedClasses['card']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-back']} */ ;
/** @type {__VLS_StyleScopedClasses['card']} */ ;
/** @type {__VLS_StyleScopedClasses['card']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-delete']} */ ;
/** @type {__VLS_StyleScopedClasses['modal-content']} */ ;
/** @type {__VLS_StyleScopedClasses['modal-content']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-cancel']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-confirm-delete']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-confirm-delete']} */ ;
// CSS variable injection 
// CSS variable injection end 
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "container" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "page-title" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "left-actions" },
});
if (__VLS_ctx.showBackButton) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (__VLS_ctx.goBack) },
        ...{ class: "btn-back" },
        'aria-label': "返回上一页",
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.svg, __VLS_intrinsicElements.svg)({
        width: "24",
        height: "24",
        viewBox: "0 0 24 24",
        fill: "none",
        xmlns: "http://www.w3.org/2000/svg",
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.path)({
        d: "M20 12H4M4 12L10 6M4 12L10 18",
        stroke: "currentColor",
        'stroke-width': "2",
        'stroke-linecap': "round",
        'stroke-linejoin': "round",
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({});
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.h2, __VLS_intrinsicElements.h2)({});
const __VLS_0 = {}.RouterLink;
/** @type {[typeof __VLS_components.RouterLink, typeof __VLS_components.RouterLink, ]} */ ;
// @ts-ignore
const __VLS_1 = __VLS_asFunctionalComponent(__VLS_0, new __VLS_0({
    ...{ class: "btn btn-primary" },
    to: "/projects/upload",
}));
const __VLS_2 = __VLS_1({
    ...{ class: "btn btn-primary" },
    to: "/projects/upload",
}, ...__VLS_functionalComponentArgsRest(__VLS_1));
__VLS_3.slots.default;
var __VLS_3;
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "card-grid" },
});
for (const [project] of __VLS_getVForSourceType((__VLS_ctx.projects))) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ onClick: (...[$event]) => {
                __VLS_ctx.handleCardClick(project.project_id);
            } },
        ...{ onTouchstart: (...[$event]) => {
                __VLS_ctx.handleTouchStart(project.project_id);
            } },
        ...{ class: "card" },
        key: (project.project_id),
        ...{ class: ({ 'card-active': __VLS_ctx.activeCardId === project.project_id }) },
        role: "button",
        'aria-label': "双击进入项目详情",
        tabindex: "0",
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "card-content" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.h3, __VLS_intrinsicElements.h3)({});
    (project.name);
    __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({
        ...{ class: ({ 'placeholder': !project.description }) },
    });
    (project.description || '暂无描述');
    const __VLS_4 = {}.RouterLink;
    /** @type {[typeof __VLS_components.RouterLink, typeof __VLS_components.RouterLink, ]} */ ;
    // @ts-ignore
    const __VLS_5 = __VLS_asFunctionalComponent(__VLS_4, new __VLS_4({
        ...{ 'onClick': {} },
        ...{ class: "btn-enter" },
        to: (`/projects/${project.project_id}`),
    }));
    const __VLS_6 = __VLS_5({
        ...{ 'onClick': {} },
        ...{ class: "btn-enter" },
        to: (`/projects/${project.project_id}`),
    }, ...__VLS_functionalComponentArgsRest(__VLS_5));
    let __VLS_8;
    let __VLS_9;
    let __VLS_10;
    const __VLS_11 = {
        onClick: () => { }
    };
    __VLS_7.slots.default;
    var __VLS_7;
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (...[$event]) => {
                __VLS_ctx.confirmDelete(project);
            } },
        ...{ class: "btn-delete" },
        title: "删除项目",
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.svg, __VLS_intrinsicElements.svg)({
        width: "16",
        height: "16",
        viewBox: "0 0 24 24",
        fill: "none",
        stroke: "currentColor",
        'stroke-width': "2",
        'stroke-linecap': "round",
        'stroke-linejoin': "round",
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.polyline, __VLS_intrinsicElements.polyline)({
        points: "3 6 5 6 21 6",
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.path, __VLS_intrinsicElements.path)({
        d: "M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2",
    });
}
if (__VLS_ctx.showDeleteModal) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "modal-overlay" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "modal-content" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.h3, __VLS_intrinsicElements.h3)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({});
    (__VLS_ctx.projectToDelete?.name);
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "modal-actions" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (__VLS_ctx.cancelDelete) },
        ...{ class: "btn-cancel" },
        disabled: (__VLS_ctx.isDeleting),
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (__VLS_ctx.handleDelete) },
        ...{ class: "btn-confirm-delete" },
        disabled: (__VLS_ctx.isDeleting),
    });
    (__VLS_ctx.isDeleting ? '删除中...' : '确认删除');
}
/** @type {__VLS_StyleScopedClasses['container']} */ ;
/** @type {__VLS_StyleScopedClasses['page-title']} */ ;
/** @type {__VLS_StyleScopedClasses['left-actions']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-back']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-primary']} */ ;
/** @type {__VLS_StyleScopedClasses['card-grid']} */ ;
/** @type {__VLS_StyleScopedClasses['card']} */ ;
/** @type {__VLS_StyleScopedClasses['card-content']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-enter']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-delete']} */ ;
/** @type {__VLS_StyleScopedClasses['modal-overlay']} */ ;
/** @type {__VLS_StyleScopedClasses['modal-content']} */ ;
/** @type {__VLS_StyleScopedClasses['modal-actions']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-cancel']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-confirm-delete']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            projects: projects,
            activeCardId: activeCardId,
            showDeleteModal: showDeleteModal,
            projectToDelete: projectToDelete,
            isDeleting: isDeleting,
            showBackButton: showBackButton,
            goBack: goBack,
            confirmDelete: confirmDelete,
            cancelDelete: cancelDelete,
            handleDelete: handleDelete,
            handleCardClick: handleCardClick,
            handleTouchStart: handleTouchStart,
        };
    },
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
});
; /* PartiallyEnd: #4569/main.vue */
