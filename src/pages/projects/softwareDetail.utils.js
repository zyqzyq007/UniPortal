export const filterTreeNodes = (nodes, keyword) => {
    if (!keyword.trim())
        return nodes;
    const q = keyword.toLowerCase();
    const walk = (node) => {
        const selfMatch = node.name.toLowerCase().includes(q);
        if (node.type === 'file') {
            return selfMatch ? node : null;
        }
        const children = (node.children || []).map(walk).filter(Boolean);
        if (selfMatch || children.length > 0) {
            return { ...node, children };
        }
        return null;
    };
    return nodes.map(walk).filter(Boolean);
};
export const getLanguageByPath = (filePath) => {
    const ext = filePath.split('.').pop()?.toLowerCase();
    if (ext === 'js' || ext === 'jsx')
        return 'javascript';
    if (ext === 'ts' || ext === 'tsx')
        return 'typescript';
    if (ext === 'html')
        return 'html';
    if (ext === 'css')
        return 'css';
    if (ext === 'json')
        return 'json';
    if (ext === 'py')
        return 'python';
    if (ext === 'md')
        return 'markdown';
    if (ext === 'vue')
        return 'html';
    return 'plaintext';
};
export const getThemeBySystem = (isDark) => (isDark ? 'vs-dark' : 'vs');
export const isBinaryPath = (filePath) => {
    const ext = filePath.split('.').pop()?.toLowerCase() || '';
    return ['png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'zip', 'rar', '7z'].includes(ext);
};
