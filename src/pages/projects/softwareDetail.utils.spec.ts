import { describe, expect, it } from 'vitest'
import {
  filterTreeNodes,
  getLanguageByPath,
  getThemeBySystem,
  isBinaryPath
} from './softwareDetail.utils'
import type { FileTreeNode } from '../../api/projects'

function makeFile(name: string): FileTreeNode {
  return { name, type: 'file', path: name }
}
function makeDir(name: string, children: FileTreeNode[]): FileTreeNode {
  return { name, type: 'dir', path: name, children }
}

describe('softwareDetail.utils', () => {
  describe('filterTreeNodes', () => {
    const tree: FileTreeNode[] = [
      makeDir('src', [
        makeFile('main.ts'),
        makeFile('utils.ts'),
        makeDir('modules', [makeFile('core.ts')])
      ]),
      makeFile('README.md'),
      makeFile('package.json')
    ]

    it('returns all nodes for empty keyword', () => {
      expect(filterTreeNodes(tree, '')).toHaveLength(3)
      expect(filterTreeNodes(tree, '  ')).toHaveLength(3)
    })

    it('matches file name directly', () => {
      const result = filterTreeNodes(tree, 'readme')
      expect(result).toHaveLength(1)
      expect(result[0].name).toBe('README.md')
    })

    it('retains parent directory when child matches', () => {
      const result = filterTreeNodes(tree, 'main')
      expect(result).toHaveLength(1)
      expect(result[0].name).toBe('src')
      expect(result[0].children).toHaveLength(1)
      expect(result[0].children![0].name).toBe('main.ts')
    })

    it('retains parent and its parent when nested child matches', () => {
      const result = filterTreeNodes(tree, 'core')
      expect(result).toHaveLength(1) // src
      expect(result[0].children).toHaveLength(1) // modules
      expect(result[0].children![0].children![0].name).toBe('core.ts')
    })

    it('is case-insensitive', () => {
      const result = filterTreeNodes(tree, 'README')
      expect(result).toHaveLength(1)
      expect(result[0].name).toBe('README.md')
    })

    it('returns empty array when no matches', () => {
      expect(filterTreeNodes(tree, 'zzz')).toHaveLength(0)
    })

    it('handles nodes with null children gracefully', () => {
      const nodes: FileTreeNode[] = [
        { name: 'dir', type: 'dir', path: 'dir', children: undefined as any }
      ]
      const result = filterTreeNodes(nodes, 'nothing')
      expect(result).toHaveLength(0)
    })

    it('returns empty array for empty tree', () => {
      expect(filterTreeNodes([], 'test')).toHaveLength(0)
    })
  })

  describe('getLanguageByPath', () => {
    it.each([
      ['file.js', 'javascript'],
      ['file.jsx', 'javascript'],
      ['file.ts', 'typescript'],
      ['file.tsx', 'typescript'],
      ['file.html', 'html'],
      ['file.css', 'css'],
      ['file.json', 'json'],
      ['file.py', 'python'],
      ['file.md', 'markdown'],
      ['file.vue', 'html'],
      ['file.unknown', 'plaintext'],
      ['noextension', 'plaintext'],
    ])('%s → %s', (path, lang) => {
      expect(getLanguageByPath(path)).toBe(lang)
    })
  })

  describe('getThemeBySystem', () => {
    it('returns vs-dark for dark mode', () => {
      expect(getThemeBySystem(true)).toBe('vs-dark')
    })

    it('returns vs for light mode', () => {
      expect(getThemeBySystem(false)).toBe('vs')
    })
  })

  describe('isBinaryPath', () => {
    it('identifies image files as binary', () => {
      expect(isBinaryPath('image.png')).toBe(true)
      expect(isBinaryPath('photo.jpg')).toBe(true)
      expect(isBinaryPath('photo.jpeg')).toBe(true)
      expect(isBinaryPath('anim.gif')).toBe(true)
      expect(isBinaryPath('img.webp')).toBe(true)
    })

    it('identifies archive files as binary', () => {
      expect(isBinaryPath('archive.zip')).toBe(true)
      expect(isBinaryPath('archive.rar')).toBe(true)
      expect(isBinaryPath('archive.7z')).toBe(true)
    })

    it('identifies PDF as binary', () => {
      expect(isBinaryPath('doc.pdf')).toBe(true)
    })

    it('returns false for text files', () => {
      expect(isBinaryPath('src/index.ts')).toBe(false)
      expect(isBinaryPath('README.md')).toBe(false)
      expect(isBinaryPath('style.css')).toBe(false)
      expect(isBinaryPath('data.json')).toBe(false)
    })

    it('returns false for unknown extensions', () => {
      expect(isBinaryPath('file.xyz')).toBe(false)
    })

    it('returns false for files with no extension', () => {
      expect(isBinaryPath('Makefile')).toBe(false)
    })
  })
})

