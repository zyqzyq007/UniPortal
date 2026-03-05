import { computed, ref, reactive, onMounted, onUnmounted } from 'vue';
import { useRoute } from 'vue-router';
import FileTree from '../../components/FileTree.vue';
import EditorPane from '../../components/EditorPane.vue';
import { getProject, updateProject, getProjectStructure } from '../../api/projects';
// Tasks API would be similar, skipping for now as not requested in core plan but keeping mock for display
import { getTasksByProject } from '../../store/mockStore';
const route = useRoute();
const projectId = computed(() => route.params.projectId);
const files = ref([]);
const project = ref();
const tasks = ref([]);
const activePath = ref('');
const activeType = ref('');
const loadError = ref(false);
const loadErrorMessage = ref('');
// 编辑状态
const isEditing = ref(false);
const saving = ref(false);
const saveError = ref('');
const editForm = reactive({
    name: '',
    description: ''
});
const editErrors = reactive({
    name: false
});
const startEdit = () => {
    if (project.value) {
        editForm.name = project.value.name;
        editForm.description = project.value.description || '';
        isEditing.value = true;
        saveError.value = '';
        editErrors.name = false;
    }
};
const cancelEdit = () => {
    isEditing.value = false;
    saveError.value = '';
};
const saveProject = async () => {
    // 验证
    if (!editForm.name.trim()) {
        editErrors.name = true;
        return;
    }
    editErrors.name = false;
    saving.value = true;
    saveError.value = '';
    try {
        const res = await updateProject(projectId.value, {
            name: editForm.name,
            description: editForm.description
        });
        project.value = res.data;
        isEditing.value = false;
    }
    catch (e) {
        saveError.value = e.message || '保存失败，请稍后重试';
        console.error(e);
    }
    finally {
        saving.value = false;
    }
};
const totalTasks = computed(() => tasks.value.length);
const runningTasks = computed(() => tasks.value.filter((t) => t.status === 'RUNNING').length);
const failedTasks = computed(() => tasks.value.filter((t) => t.status === 'FAILED').length);
// 滚动交互逻辑
const containerRef = ref(null);
const showScrollIndicator = ref(false);
const contentOffset = ref(0);
let lastScrollTop = 0;
const checkScroll = () => {
    const el = containerRef.value;
    if (!el)
        return;
    // 检查是否可滚动且未滚动到底部 (容差 20px)
    const isScrollable = el.scrollHeight > el.clientHeight;
    const isAtBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 20;
    showScrollIndicator.value = isScrollable && !isAtBottom;
};
const handleScroll = () => {
    checkScroll();
    // 简单的滚动反馈效果
    const el = containerRef.value;
    if (el) {
        const currentScroll = el.scrollTop;
        const diff = currentScroll - lastScrollTop;
        // 向下滑动时产生微小的位移反馈，但限制最大值防止抖动
        if (diff > 0 && currentScroll < 100) {
            contentOffset.value = Math.min(diff * 0.1, 5);
        }
        else {
            contentOffset.value = 0;
        }
        lastScrollTop = currentScroll;
    }
};
const scrollToBottom = () => {
    containerRef.value?.scrollTo({
        top: containerRef.value.scrollHeight,
        behavior: 'smooth'
    });
};
const fetchProjectData = async () => {
    loadError.value = false;
    loadErrorMessage.value = '';
    if (!projectId.value) {
        loadError.value = true;
        loadErrorMessage.value = '无效的项目ID';
        return;
    }
    try {
        const [projRes, structRes] = await Promise.all([
            getProject(projectId.value),
            getProjectStructure(projectId.value).catch(() => ({ data: { name: 'root', type: 'directory', children: [] } }))
        ]);
        project.value = projRes.data;
        const root = structRes.data;
        files.value = root.children || []; // Display children of root
        // Keep mock tasks for now
        tasks.value = getTasksByProject(projectId.value);
        const firstFile = findFirstFile(files.value);
        if (firstFile)
            activePath.value = firstFile;
    }
    catch (e) {
        console.error('Failed to load project', e);
        loadError.value = true;
        if (e.code === 404) {
            loadErrorMessage.value = '未找到该项目，可能已被删除或无权限访问';
        }
        else if (e.code === 403) {
            loadErrorMessage.value = '您没有权限访问该项目';
        }
        else if (e.code === 503) {
            loadErrorMessage.value = '后端服务不可用，请确认服务已启动并监听 8080';
        }
        else {
            loadErrorMessage.value = e.message || '加载项目失败，请稍后重试';
        }
    }
};
onMounted(() => {
    fetchProjectData();
    // 初始化检查滚动状态 (延迟确保 DOM 渲染)
    setTimeout(checkScroll, 100);
    window.addEventListener('resize', checkScroll);
});
onUnmounted(() => {
    window.removeEventListener('resize', checkScroll);
});
const onOpenFile = (payload) => {
    activePath.value = payload.path;
    activeType.value = payload.type;
};
const findFirstFile = (list) => {
    for (const n of list) {
        if (n.type === 'file')
            return n.name;
        if (n.type === 'dir' && n.children && n.children.length) {
            const sub = findFirstFile(n.children.map((c) => ({ ...c, name: `${n.name}/${c.name}` })));
            if (sub)
                return sub;
        }
    }
    return null;
};
const isNotFound = computed(() => loadErrorMessage.value.includes('未找到') || loadErrorMessage.value.includes('无效'));
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
/** @type {__VLS_StyleScopedClasses['btn-icon']} */ ;
/** @type {__VLS_StyleScopedClasses['project-header']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-outline']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-primary']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-primary']} */ ;
/** @type {__VLS_StyleScopedClasses['card-header']} */ ;
/** @type {__VLS_StyleScopedClasses['editor-card']} */ ;
/** @type {__VLS_StyleScopedClasses['action-card']} */ ;
/** @type {__VLS_StyleScopedClasses['action-card']} */ ;
/** @type {__VLS_StyleScopedClasses['icon']} */ ;
/** @type {__VLS_StyleScopedClasses['info']} */ ;
/** @type {__VLS_StyleScopedClasses['stats-card']} */ ;
/** @type {__VLS_StyleScopedClasses['stat-item']} */ ;
/** @type {__VLS_StyleScopedClasses['stat-item']} */ ;
/** @type {__VLS_StyleScopedClasses['stat-item']} */ ;
/** @type {__VLS_StyleScopedClasses['value']} */ ;
/** @type {__VLS_StyleScopedClasses['stat-item']} */ ;
/** @type {__VLS_StyleScopedClasses['value']} */ ;
/** @type {__VLS_StyleScopedClasses['stats-footer']} */ ;
/** @type {__VLS_StyleScopedClasses['stats-footer']} */ ;
/** @type {__VLS_StyleScopedClasses['link']} */ ;
/** @type {__VLS_StyleScopedClasses['main-layout']} */ ;
/** @type {__VLS_StyleScopedClasses['quick-actions']} */ ;
/** @type {__VLS_StyleScopedClasses['scroll-mask']} */ ;
/** @type {__VLS_StyleScopedClasses['error-content']} */ ;
// CSS variable injection 
// CSS variable injection end 
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ onScroll: (__VLS_ctx.handleScroll) },
    ...{ class: "dashboard-container" },
    ref: "containerRef",
});
/** @type {typeof __VLS_ctx.containerRef} */ ;
if (__VLS_ctx.loadError) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "error-container" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "error-content" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "error-icon" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.h2, __VLS_intrinsicElements.h2)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({
        ...{ class: "error-msg" },
    });
    (__VLS_ctx.loadErrorMessage);
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "error-actions" },
    });
    if (!__VLS_ctx.isNotFound) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
            ...{ onClick: (__VLS_ctx.fetchProjectData) },
            ...{ class: "btn btn-primary" },
        });
    }
    const __VLS_0 = {}.RouterLink;
    /** @type {[typeof __VLS_components.RouterLink, typeof __VLS_components.RouterLink, ]} */ ;
    // @ts-ignore
    const __VLS_1 = __VLS_asFunctionalComponent(__VLS_0, new __VLS_0({
        ...{ class: "btn btn-outline" },
        to: "/projects",
    }));
    const __VLS_2 = __VLS_1({
        ...{ class: "btn btn-outline" },
        to: "/projects",
    }, ...__VLS_functionalComponentArgsRest(__VLS_1));
    __VLS_3.slots.default;
    var __VLS_3;
}
else {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "dashboard" },
        ...{ style: ({ transform: `translateY(${__VLS_ctx.contentOffset}px)` }) },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.header, __VLS_intrinsicElements.header)({
        ...{ class: "project-header" },
    });
    if (!__VLS_ctx.isEditing) {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "header-content" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "title-row" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.h2, __VLS_intrinsicElements.h2)({});
        (__VLS_ctx.project?.name || '加载中...');
        __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
            ...{ onClick: (__VLS_ctx.startEdit) },
            ...{ class: "btn-icon" },
            title: "编辑项目信息",
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({
            ...{ class: "desc" },
        });
        (__VLS_ctx.project?.description || '暂无描述');
    }
    else {
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "header-content edit-mode" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "form-group" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.input)({
            ...{ class: "input-name" },
            placeholder: "项目名称（必填，最大50字符）",
            maxlength: "50",
        });
        (__VLS_ctx.editForm.name);
        if (__VLS_ctx.editErrors.name) {
            __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
                ...{ class: "error-text" },
            });
        }
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "form-group" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.textarea, __VLS_intrinsicElements.textarea)({
            value: (__VLS_ctx.editForm.description),
            ...{ class: "input-desc" },
            placeholder: "项目描述（最大500字符）",
            maxlength: "500",
            rows: "3",
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
            ...{ class: "edit-actions" },
        });
        __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
            ...{ onClick: (__VLS_ctx.saveProject) },
            ...{ class: "btn btn-primary btn-sm" },
            disabled: (__VLS_ctx.saving),
        });
        (__VLS_ctx.saving ? '保存中...' : '保存');
        __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
            ...{ onClick: (__VLS_ctx.cancelEdit) },
            ...{ class: "btn btn-outline btn-sm" },
            disabled: (__VLS_ctx.saving),
        });
        if (__VLS_ctx.saveError) {
            __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({
                ...{ class: "error-text" },
            });
            (__VLS_ctx.saveError);
        }
    }
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "header-right" },
    });
    const __VLS_4 = {}.RouterLink;
    /** @type {[typeof __VLS_components.RouterLink, typeof __VLS_components.RouterLink, ]} */ ;
    // @ts-ignore
    const __VLS_5 = __VLS_asFunctionalComponent(__VLS_4, new __VLS_4({
        ...{ class: "btn btn-outline" },
        to: "/projects",
    }));
    const __VLS_6 = __VLS_5({
        ...{ class: "btn btn-outline" },
        to: "/projects",
    }, ...__VLS_functionalComponentArgsRest(__VLS_5));
    __VLS_7.slots.default;
    var __VLS_7;
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "main-layout" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "left-column" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "card file-tree-card" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "card-header" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.h3, __VLS_intrinsicElements.h3)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "tree-container" },
    });
    /** @type {[typeof FileTree, ]} */ ;
    // @ts-ignore
    const __VLS_8 = __VLS_asFunctionalComponent(FileTree, new FileTree({
        ...{ 'onOpenFile': {} },
        nodes: (__VLS_ctx.files),
        activePath: (__VLS_ctx.activePath),
    }));
    const __VLS_9 = __VLS_8({
        ...{ 'onOpenFile': {} },
        nodes: (__VLS_ctx.files),
        activePath: (__VLS_ctx.activePath),
    }, ...__VLS_functionalComponentArgsRest(__VLS_8));
    let __VLS_11;
    let __VLS_12;
    let __VLS_13;
    const __VLS_14 = {
        onOpenFile: (__VLS_ctx.onOpenFile)
    };
    var __VLS_10;
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "quick-actions" },
    });
    const __VLS_15 = {}.RouterLink;
    /** @type {[typeof __VLS_components.RouterLink, typeof __VLS_components.RouterLink, ]} */ ;
    // @ts-ignore
    const __VLS_16 = __VLS_asFunctionalComponent(__VLS_15, new __VLS_15({
        to: (`/projects/${__VLS_ctx.projectId}/tools`),
        ...{ class: "action-card tool-card" },
    }));
    const __VLS_17 = __VLS_16({
        to: (`/projects/${__VLS_ctx.projectId}/tools`),
        ...{ class: "action-card tool-card" },
    }, ...__VLS_functionalComponentArgsRest(__VLS_16));
    __VLS_18.slots.default;
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "icon" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "info" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.h4, __VLS_intrinsicElements.h4)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "arrow" },
    });
    var __VLS_18;
    const __VLS_19 = {}.RouterLink;
    /** @type {[typeof __VLS_components.RouterLink, typeof __VLS_components.RouterLink, ]} */ ;
    // @ts-ignore
    const __VLS_20 = __VLS_asFunctionalComponent(__VLS_19, new __VLS_19({
        to: (`/projects/${__VLS_ctx.projectId}/tasks`),
        ...{ class: "action-card task-card" },
    }));
    const __VLS_21 = __VLS_20({
        to: (`/projects/${__VLS_ctx.projectId}/tasks`),
        ...{ class: "action-card task-card" },
    }, ...__VLS_functionalComponentArgsRest(__VLS_20));
    __VLS_22.slots.default;
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "icon" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "info" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.h4, __VLS_intrinsicElements.h4)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "arrow" },
    });
    var __VLS_22;
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "right-column" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "card editor-card" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.h3, __VLS_intrinsicElements.h3)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "editor-container" },
    });
    /** @type {[typeof EditorPane, ]} */ ;
    // @ts-ignore
    const __VLS_23 = __VLS_asFunctionalComponent(EditorPane, new EditorPane({
        projectId: (__VLS_ctx.projectId),
        filePath: (__VLS_ctx.activePath),
        fileType: (__VLS_ctx.activeType),
    }));
    const __VLS_24 = __VLS_23({
        projectId: (__VLS_ctx.projectId),
        filePath: (__VLS_ctx.activePath),
        fileType: (__VLS_ctx.activeType),
    }, ...__VLS_functionalComponentArgsRest(__VLS_23));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "card stats-card" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.h3, __VLS_intrinsicElements.h3)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "stats-list" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "stat-item total" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "label" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "value" },
    });
    (__VLS_ctx.totalTasks);
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "stat-item running" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "label" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "value" },
    });
    (__VLS_ctx.runningTasks);
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "stat-item failed" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "label" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "value" },
    });
    (__VLS_ctx.failedTasks);
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "stats-footer" },
    });
    const __VLS_26 = {}.RouterLink;
    /** @type {[typeof __VLS_components.RouterLink, typeof __VLS_components.RouterLink, ]} */ ;
    // @ts-ignore
    const __VLS_27 = __VLS_asFunctionalComponent(__VLS_26, new __VLS_26({
        to: (`/projects/${__VLS_ctx.projectId}/tasks`),
        ...{ class: "link" },
    }));
    const __VLS_28 = __VLS_27({
        to: (`/projects/${__VLS_ctx.projectId}/tasks`),
        ...{ class: "link" },
    }, ...__VLS_functionalComponentArgsRest(__VLS_27));
    __VLS_29.slots.default;
    var __VLS_29;
}
const __VLS_30 = {}.Transition;
/** @type {[typeof __VLS_components.Transition, typeof __VLS_components.Transition, ]} */ ;
// @ts-ignore
const __VLS_31 = __VLS_asFunctionalComponent(__VLS_30, new __VLS_30({
    name: "fade",
}));
const __VLS_32 = __VLS_31({
    name: "fade",
}, ...__VLS_functionalComponentArgsRest(__VLS_31));
__VLS_33.slots.default;
if (__VLS_ctx.showScrollIndicator) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ onClick: (__VLS_ctx.scrollToBottom) },
        ...{ class: "scroll-indicator" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "arrow-down" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "text" },
    });
}
var __VLS_33;
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "scroll-mask" },
    ...{ class: ({ visible: __VLS_ctx.showScrollIndicator }) },
});
/** @type {__VLS_StyleScopedClasses['dashboard-container']} */ ;
/** @type {__VLS_StyleScopedClasses['error-container']} */ ;
/** @type {__VLS_StyleScopedClasses['error-content']} */ ;
/** @type {__VLS_StyleScopedClasses['error-icon']} */ ;
/** @type {__VLS_StyleScopedClasses['error-msg']} */ ;
/** @type {__VLS_StyleScopedClasses['error-actions']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-primary']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-outline']} */ ;
/** @type {__VLS_StyleScopedClasses['dashboard']} */ ;
/** @type {__VLS_StyleScopedClasses['project-header']} */ ;
/** @type {__VLS_StyleScopedClasses['header-content']} */ ;
/** @type {__VLS_StyleScopedClasses['title-row']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-icon']} */ ;
/** @type {__VLS_StyleScopedClasses['desc']} */ ;
/** @type {__VLS_StyleScopedClasses['header-content']} */ ;
/** @type {__VLS_StyleScopedClasses['edit-mode']} */ ;
/** @type {__VLS_StyleScopedClasses['form-group']} */ ;
/** @type {__VLS_StyleScopedClasses['input-name']} */ ;
/** @type {__VLS_StyleScopedClasses['error-text']} */ ;
/** @type {__VLS_StyleScopedClasses['form-group']} */ ;
/** @type {__VLS_StyleScopedClasses['input-desc']} */ ;
/** @type {__VLS_StyleScopedClasses['edit-actions']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-primary']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-sm']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-outline']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-sm']} */ ;
/** @type {__VLS_StyleScopedClasses['error-text']} */ ;
/** @type {__VLS_StyleScopedClasses['header-right']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
/** @type {__VLS_StyleScopedClasses['btn-outline']} */ ;
/** @type {__VLS_StyleScopedClasses['main-layout']} */ ;
/** @type {__VLS_StyleScopedClasses['left-column']} */ ;
/** @type {__VLS_StyleScopedClasses['card']} */ ;
/** @type {__VLS_StyleScopedClasses['file-tree-card']} */ ;
/** @type {__VLS_StyleScopedClasses['card-header']} */ ;
/** @type {__VLS_StyleScopedClasses['tree-container']} */ ;
/** @type {__VLS_StyleScopedClasses['quick-actions']} */ ;
/** @type {__VLS_StyleScopedClasses['action-card']} */ ;
/** @type {__VLS_StyleScopedClasses['tool-card']} */ ;
/** @type {__VLS_StyleScopedClasses['icon']} */ ;
/** @type {__VLS_StyleScopedClasses['info']} */ ;
/** @type {__VLS_StyleScopedClasses['arrow']} */ ;
/** @type {__VLS_StyleScopedClasses['action-card']} */ ;
/** @type {__VLS_StyleScopedClasses['task-card']} */ ;
/** @type {__VLS_StyleScopedClasses['icon']} */ ;
/** @type {__VLS_StyleScopedClasses['info']} */ ;
/** @type {__VLS_StyleScopedClasses['arrow']} */ ;
/** @type {__VLS_StyleScopedClasses['right-column']} */ ;
/** @type {__VLS_StyleScopedClasses['card']} */ ;
/** @type {__VLS_StyleScopedClasses['editor-card']} */ ;
/** @type {__VLS_StyleScopedClasses['editor-container']} */ ;
/** @type {__VLS_StyleScopedClasses['card']} */ ;
/** @type {__VLS_StyleScopedClasses['stats-card']} */ ;
/** @type {__VLS_StyleScopedClasses['stats-list']} */ ;
/** @type {__VLS_StyleScopedClasses['stat-item']} */ ;
/** @type {__VLS_StyleScopedClasses['total']} */ ;
/** @type {__VLS_StyleScopedClasses['label']} */ ;
/** @type {__VLS_StyleScopedClasses['value']} */ ;
/** @type {__VLS_StyleScopedClasses['stat-item']} */ ;
/** @type {__VLS_StyleScopedClasses['running']} */ ;
/** @type {__VLS_StyleScopedClasses['label']} */ ;
/** @type {__VLS_StyleScopedClasses['value']} */ ;
/** @type {__VLS_StyleScopedClasses['stat-item']} */ ;
/** @type {__VLS_StyleScopedClasses['failed']} */ ;
/** @type {__VLS_StyleScopedClasses['label']} */ ;
/** @type {__VLS_StyleScopedClasses['value']} */ ;
/** @type {__VLS_StyleScopedClasses['stats-footer']} */ ;
/** @type {__VLS_StyleScopedClasses['link']} */ ;
/** @type {__VLS_StyleScopedClasses['scroll-indicator']} */ ;
/** @type {__VLS_StyleScopedClasses['arrow-down']} */ ;
/** @type {__VLS_StyleScopedClasses['text']} */ ;
/** @type {__VLS_StyleScopedClasses['scroll-mask']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            FileTree: FileTree,
            EditorPane: EditorPane,
            projectId: projectId,
            files: files,
            project: project,
            activePath: activePath,
            activeType: activeType,
            loadError: loadError,
            loadErrorMessage: loadErrorMessage,
            isEditing: isEditing,
            saving: saving,
            saveError: saveError,
            editForm: editForm,
            editErrors: editErrors,
            startEdit: startEdit,
            cancelEdit: cancelEdit,
            saveProject: saveProject,
            totalTasks: totalTasks,
            runningTasks: runningTasks,
            failedTasks: failedTasks,
            containerRef: containerRef,
            showScrollIndicator: showScrollIndicator,
            contentOffset: contentOffset,
            handleScroll: handleScroll,
            scrollToBottom: scrollToBottom,
            fetchProjectData: fetchProjectData,
            onOpenFile: onOpenFile,
            isNotFound: isNotFound,
        };
    },
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
});
; /* PartiallyEnd: #4569/main.vue */
