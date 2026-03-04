/// <reference types="../../../node_modules/.vue-global-types/vue_3.5_0_0_0.d.ts" />
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import CodeEditor from '../../components/CodeEditor.vue';
import SoftwareTreeNode from '../../components/software-detail/SoftwareTreeNode.vue';
import { getItemFileContent, getItemStructure, operateItemNode } from '../../api/projects';
import { filterTreeNodes, getLanguageByPath, getThemeBySystem, isBinaryPath } from './softwareDetail.utils';
import { pushFrontLog } from '../../utils/frontLogger';
const route = useRoute();
const router = useRouter();
const projectId = computed(() => route.params.projectId);
const itemId = computed(() => route.params.itemId);
const itemName = computed(() => route.query.itemName || '项目详情');
const nodes = ref([]);
const expandedMap = reactive({});
const selectedFilePath = ref('');
const editorContent = ref('');
const keyword = ref('');
const loadingMask = ref(false);
const leftWidth = ref(30);
const language = computed(() => getLanguageByPath(selectedFilePath.value));
const theme = computed(() => getThemeBySystem(window.matchMedia('(prefers-color-scheme: dark)').matches));
const filteredNodes = computed(() => filterTreeNodes(nodes.value, keyword.value));
const currentMeta = reactive({
    language: '-',
    size: 0,
    updated_at: ''
});
const binarySource = ref('');
const binaryKind = ref('none');
const notice = reactive({ visible: false, message: '', code: 0 });
const menuVisible = ref(false);
const menuX = ref(0);
const menuY = ref(0);
const activeNode = ref(null);
const formatBytes = (bytes) => {
    if (!bytes)
        return '-';
    if (bytes < 1024)
        return `${bytes} B`;
    if (bytes < 1024 * 1024)
        return `${(bytes / 1024).toFixed(2)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
};
const showError = (error, fallback) => {
    const code = Number(error?.code || 500);
    const message = error?.message || fallback;
    notice.visible = true;
    notice.message = message;
    notice.code = code;
    pushFrontLog({ level: 'error', message, code, detail: JSON.stringify(error?.data || {}) });
};
const fetchRoot = async () => {
    loadingMask.value = true;
    try {
        const res = await getItemStructure(projectId.value, itemId.value, '');
        nodes.value = res.data.children || [];
        expandedMap[''] = true;
        const readme = nodes.value.find((n) => n.type === 'file' && n.name.toLowerCase() === 'readme.md');
        if (readme) {
            await openFile(readme);
        }
    }
    catch (error) {
        console.error('load tree failed', error);
        showError(error, '目录加载失败');
    }
    finally {
        loadingMask.value = false;
    }
};
const fetchChildren = async (node) => {
    const res = await getItemStructure(projectId.value, itemId.value, node.path);
    node.children = res.data.children || [];
};
const toggleDir = async (node) => {
    if (node.type !== 'dir')
        return;
    const next = !expandedMap[node.path];
    expandedMap[node.path] = next;
    if (next && (!node.children || node.children.length === 0)) {
        try {
            loadingMask.value = true;
            await fetchChildren(node);
        }
        catch (error) {
            console.error('load children failed', error);
            showError(error, '目录加载失败');
        }
        finally {
            loadingMask.value = false;
        }
    }
};
const applyFileData = (data) => {
    currentMeta.language = data.language || '-';
    currentMeta.size = data.size || 0;
    currentMeta.updated_at = data.updated_at || '';
    if (data.kind === 'binary') {
        const mime = data.mime_type || 'application/octet-stream';
        const src = `data:${mime};base64,${data.content_base64 || ''}`;
        binarySource.value = src;
        if (mime.startsWith('image/'))
            binaryKind.value = 'image';
        else if (mime === 'application/pdf')
            binaryKind.value = 'pdf';
        else
            binaryKind.value = 'other';
        editorContent.value = '';
        return;
    }
    binaryKind.value = 'none';
    binarySource.value = '';
    editorContent.value = data.content || '';
};
const openFile = async (node) => {
    selectedFilePath.value = node.path;
    menuVisible.value = false;
    try {
        loadingMask.value = true;
        if (isBinaryPath(node.path)) {
            const res = await getItemFileContent(projectId.value, itemId.value, node.path);
            applyFileData(res.data);
            return;
        }
        let res;
        try {
            res = await getItemFileContent(projectId.value, itemId.value, node.path);
        }
        catch (error) {
            if (error.code === 413) {
                const ok = window.confirm('文件超过 1 MB，是否继续分片加载？');
                if (!ok)
                    return;
                let offset = 0;
                const chunk = 256 * 1024;
                let content = '';
                while (true) {
                    const chunkRes = await getItemFileContent(projectId.value, itemId.value, node.path, {
                        allowLarge: true,
                        offset,
                        limit: chunk
                    });
                    content += chunkRes.data.content || '';
                    if (chunkRes.data.eof) {
                        res = { data: { ...chunkRes.data, content } };
                        break;
                    }
                    offset += chunkRes.data.limit;
                }
            }
            else {
                throw error;
            }
        }
        applyFileData(res.data);
    }
    catch (error) {
        console.error('open file failed', error);
        showError(error, '文件打开失败');
    }
    finally {
        loadingMask.value = false;
    }
};
const goBack = () => {
    router.push({
        name: 'ProjectItems',
        params: { projectId: projectId.value },
        query: route.query
    });
};
const openContextMenu = (event, node) => {
    activeNode.value = node;
    menuX.value = event.clientX;
    menuY.value = event.clientY;
    menuVisible.value = true;
};
const refreshNode = async () => {
    if (!activeNode.value) {
        await fetchRoot();
        return;
    }
    const p = activeNode.value.type === 'dir' ? activeNode.value.path : activeNode.value.path.split('/').slice(0, -1).join('/');
    if (!p) {
        await fetchRoot();
        return;
    }
    const res = await getItemStructure(projectId.value, itemId.value, p);
    const walk = (list) => {
        for (const n of list) {
            if (n.path === p) {
                n.children = res.data.children || [];
                return true;
            }
            if (n.children?.length && walk(n.children))
                return true;
        }
        return false;
    };
    walk(nodes.value);
};
const handleNodeAction = async (action) => {
    if (!activeNode.value)
        return;
    let payload = {
        action,
        path: activeNode.value.path
    };
    if (action === 'new_file' || action === 'new_folder') {
        const name = window.prompt(action === 'new_file' ? '请输入文件名' : '请输入文件夹名');
        if (!name)
            return;
        payload.path = `${activeNode.value.type === 'dir' ? activeNode.value.path : activeNode.value.path.split('/').slice(0, -1).join('/')}/${name}`.replace(/^\/+/, '');
    }
    if (action === 'rename') {
        const name = window.prompt('请输入新名称', activeNode.value.name);
        if (!name)
            return;
        payload.newName = name;
    }
    if (action === 'delete') {
        const ok = window.confirm(`确认删除 ${activeNode.value.name} 吗？`);
        if (!ok)
            return;
    }
    try {
        loadingMask.value = true;
        await operateItemNode(projectId.value, itemId.value, payload);
        await refreshNode();
    }
    catch (error) {
        console.error('node operation failed', error);
        showError(error, '文件操作失败');
    }
    finally {
        loadingMask.value = false;
        menuVisible.value = false;
    }
};
const copyRelativePath = async () => {
    if (!activeNode.value)
        return;
    await navigator.clipboard.writeText(activeNode.value.path);
    menuVisible.value = false;
};
const onDocClick = () => {
    menuVisible.value = false;
};
const startDrag = (event) => {
    const startX = event.clientX;
    const start = leftWidth.value;
    const onMove = (e) => {
        const delta = e.clientX - startX;
        const percent = start + (delta / window.innerWidth) * 100;
        leftWidth.value = Math.min(60, Math.max(20, percent));
    };
    const onUp = () => {
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
};
onMounted(() => {
    document.addEventListener('click', onDocClick);
    fetchRoot();
});
onBeforeUnmount(() => {
    document.removeEventListener('click', onDocClick);
});
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
/** @type {__VLS_StyleScopedClasses['context-menu']} */ ;
/** @type {__VLS_StyleScopedClasses['context-menu']} */ ;
/** @type {__VLS_StyleScopedClasses['viewer-meta']} */ ;
// CSS variable injection 
// CSS variable injection end 
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "detail-page" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "top-bar" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "breadcrumbs" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
    ...{ onClick: (__VLS_ctx.goBack) },
    ...{ class: "crumb-btn" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
    ...{ class: "current" },
});
(__VLS_ctx.itemName);
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "status" },
});
(__VLS_ctx.selectedFilePath || '未选择文件');
if (__VLS_ctx.notice.visible) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "notice-bar" },
    });
    (__VLS_ctx.notice.message);
    (__VLS_ctx.notice.code);
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "split-wrap" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "left-card" },
    ...{ style: ({ width: `${__VLS_ctx.leftWidth}%` }) },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "card-header" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "tree-toolbar" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.input)({
    ...{ class: "search-input" },
    placeholder: "搜索文件或文件夹",
});
(__VLS_ctx.keyword);
__VLS_asFunctionalElement(__VLS_intrinsicElements.ul, __VLS_intrinsicElements.ul)({
    ...{ class: "tree-root" },
});
for (const [node] of __VLS_getVForSourceType((__VLS_ctx.filteredNodes))) {
    /** @type {[typeof SoftwareTreeNode, ]} */ ;
    // @ts-ignore
    const __VLS_0 = __VLS_asFunctionalComponent(SoftwareTreeNode, new SoftwareTreeNode({
        ...{ 'onToggleDir': {} },
        ...{ 'onOpenFile': {} },
        ...{ 'onContextmenu': {} },
        key: (node.path),
        node: (node),
        selectedPath: (__VLS_ctx.selectedFilePath),
        expandedMap: (__VLS_ctx.expandedMap),
        keyword: (__VLS_ctx.keyword),
    }));
    const __VLS_1 = __VLS_0({
        ...{ 'onToggleDir': {} },
        ...{ 'onOpenFile': {} },
        ...{ 'onContextmenu': {} },
        key: (node.path),
        node: (node),
        selectedPath: (__VLS_ctx.selectedFilePath),
        expandedMap: (__VLS_ctx.expandedMap),
        keyword: (__VLS_ctx.keyword),
    }, ...__VLS_functionalComponentArgsRest(__VLS_0));
    let __VLS_3;
    let __VLS_4;
    let __VLS_5;
    const __VLS_6 = {
        onToggleDir: (__VLS_ctx.toggleDir)
    };
    const __VLS_7 = {
        onOpenFile: (__VLS_ctx.openFile)
    };
    const __VLS_8 = {
        onContextmenu: (__VLS_ctx.openContextMenu)
    };
    var __VLS_2;
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ onMousedown: (__VLS_ctx.startDrag) },
    ...{ class: "splitter" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "right-card" },
    ...{ style: ({ width: `${100 - __VLS_ctx.leftWidth}%` }) },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "viewer-meta" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({});
(__VLS_ctx.selectedFilePath || '-');
__VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({});
(__VLS_ctx.currentMeta.language);
__VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({});
(__VLS_ctx.formatBytes(__VLS_ctx.currentMeta.size));
__VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({});
(__VLS_ctx.currentMeta.updated_at || '-');
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "viewer-body" },
});
if (__VLS_ctx.binaryKind === 'image') {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "binary-view" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.img)({
        src: (__VLS_ctx.binarySource),
        ...{ class: "preview-image" },
    });
}
else if (__VLS_ctx.binaryKind === 'pdf') {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "binary-view" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.iframe, __VLS_intrinsicElements.iframe)({
        src: (__VLS_ctx.binarySource),
        ...{ class: "preview-pdf" },
    });
}
else if (__VLS_ctx.binaryKind === 'other') {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "empty-view" },
    });
}
else if (!__VLS_ctx.selectedFilePath) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "empty-view" },
    });
}
else {
    /** @type {[typeof CodeEditor, ]} */ ;
    // @ts-ignore
    const __VLS_9 = __VLS_asFunctionalComponent(CodeEditor, new CodeEditor({
        value: (__VLS_ctx.editorContent),
        language: (__VLS_ctx.language),
        theme: (__VLS_ctx.theme),
    }));
    const __VLS_10 = __VLS_9({
        value: (__VLS_ctx.editorContent),
        language: (__VLS_ctx.language),
        theme: (__VLS_ctx.theme),
    }, ...__VLS_functionalComponentArgsRest(__VLS_9));
}
if (__VLS_ctx.menuVisible) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "context-menu" },
        ...{ style: ({ left: `${__VLS_ctx.menuX}px`, top: `${__VLS_ctx.menuY}px` }) },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (...[$event]) => {
                if (!(__VLS_ctx.menuVisible))
                    return;
                __VLS_ctx.handleNodeAction('new_file');
            } },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (...[$event]) => {
                if (!(__VLS_ctx.menuVisible))
                    return;
                __VLS_ctx.handleNodeAction('new_folder');
            } },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (...[$event]) => {
                if (!(__VLS_ctx.menuVisible))
                    return;
                __VLS_ctx.handleNodeAction('rename');
            } },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (...[$event]) => {
                if (!(__VLS_ctx.menuVisible))
                    return;
                __VLS_ctx.handleNodeAction('delete');
            } },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
        ...{ onClick: (__VLS_ctx.copyRelativePath) },
    });
}
if (__VLS_ctx.loadingMask) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "loading-mask" },
    });
}
/** @type {__VLS_StyleScopedClasses['detail-page']} */ ;
/** @type {__VLS_StyleScopedClasses['top-bar']} */ ;
/** @type {__VLS_StyleScopedClasses['breadcrumbs']} */ ;
/** @type {__VLS_StyleScopedClasses['crumb-btn']} */ ;
/** @type {__VLS_StyleScopedClasses['current']} */ ;
/** @type {__VLS_StyleScopedClasses['status']} */ ;
/** @type {__VLS_StyleScopedClasses['notice-bar']} */ ;
/** @type {__VLS_StyleScopedClasses['split-wrap']} */ ;
/** @type {__VLS_StyleScopedClasses['left-card']} */ ;
/** @type {__VLS_StyleScopedClasses['card-header']} */ ;
/** @type {__VLS_StyleScopedClasses['tree-toolbar']} */ ;
/** @type {__VLS_StyleScopedClasses['search-input']} */ ;
/** @type {__VLS_StyleScopedClasses['tree-root']} */ ;
/** @type {__VLS_StyleScopedClasses['splitter']} */ ;
/** @type {__VLS_StyleScopedClasses['right-card']} */ ;
/** @type {__VLS_StyleScopedClasses['viewer-meta']} */ ;
/** @type {__VLS_StyleScopedClasses['viewer-body']} */ ;
/** @type {__VLS_StyleScopedClasses['binary-view']} */ ;
/** @type {__VLS_StyleScopedClasses['preview-image']} */ ;
/** @type {__VLS_StyleScopedClasses['binary-view']} */ ;
/** @type {__VLS_StyleScopedClasses['preview-pdf']} */ ;
/** @type {__VLS_StyleScopedClasses['empty-view']} */ ;
/** @type {__VLS_StyleScopedClasses['empty-view']} */ ;
/** @type {__VLS_StyleScopedClasses['context-menu']} */ ;
/** @type {__VLS_StyleScopedClasses['loading-mask']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            CodeEditor: CodeEditor,
            SoftwareTreeNode: SoftwareTreeNode,
            itemName: itemName,
            expandedMap: expandedMap,
            selectedFilePath: selectedFilePath,
            editorContent: editorContent,
            keyword: keyword,
            loadingMask: loadingMask,
            leftWidth: leftWidth,
            language: language,
            theme: theme,
            filteredNodes: filteredNodes,
            currentMeta: currentMeta,
            binarySource: binarySource,
            binaryKind: binaryKind,
            notice: notice,
            menuVisible: menuVisible,
            menuX: menuX,
            menuY: menuY,
            formatBytes: formatBytes,
            toggleDir: toggleDir,
            openFile: openFile,
            goBack: goBack,
            openContextMenu: openContextMenu,
            handleNodeAction: handleNodeAction,
            copyRelativePath: copyRelativePath,
            startDrag: startDrag,
        };
    },
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
});
; /* PartiallyEnd: #4569/main.vue */
