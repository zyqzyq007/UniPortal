import { describe, expect, it } from 'vitest';
import { filterTreeNodes, getLanguageByPath, getThemeBySystem } from './softwareDetail.utils';
describe('softwareDetail.utils', () => {
    it('目录树搜索可命中并保留父级节点', () => {
        const tree = [
            {
                name: 'src',
                type: 'dir',
                path: 'src',
                children: [{ name: 'main.ts', type: 'file', path: 'src/main.ts' }]
            },
            { name: 'README.md', type: 'file', path: 'README.md' }
        ];
        const result = filterTreeNodes(tree, 'main');
        expect(result).toHaveLength(1);
        expect(result[0].name).toBe('src');
        expect(result[0].children?.[0].name).toBe('main.ts');
    });
    it('语言识别与主题切换正确', () => {
        expect(getLanguageByPath('src/index.ts')).toBe('typescript');
        expect(getLanguageByPath('docs/readme.md')).toBe('markdown');
        expect(getThemeBySystem(true)).toBe('vs-dark');
        expect(getThemeBySystem(false)).toBe('vs');
    });
});
