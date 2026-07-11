import { recoverZipFilename } from '../src/utils/encoding'

describe('recoverZipFilename', () => {
  // ── GBK recovery ──
  // When adm-zip reads a GBK-encoded filename, it interprets the bytes
  // as Latin-1, producing mojibake. This function reverses the process.

  it('recovers 中文 from GBK→Latin1 garbled text', () => {
    expect(recoverZipFilename('ÖÐÎÄ')).toBe('中文')
  })

  it('recovers 测试文档 from GBK→Latin1 garbled text', () => {
    expect(recoverZipFilename('²âÊÔÎÄµµ')).toBe('测试文档')
  })

  it('recovers 简体中文 from GBK→Latin1 garbled text', () => {
    expect(recoverZipFilename('¼òÌåÖÐÎÄ')).toBe('简体中文')
  })

  it('recovers 需求说明 from GBK→Latin1 garbled text', () => {
    expect(recoverZipFilename('ÐèÇóËµÃ÷')).toBe('需求说明')
  })

  it('recovers 你好世界 from GBK→Latin1 garbled text', () => {
    expect(recoverZipFilename('ÄãºÃÊÀ½ç')).toBe('你好世界')
  })

  // ── Pass-through tests ──

  it('passes through ASCII strings unchanged', () => {
    expect(recoverZipFilename('src/index.ts')).toBe('src/index.ts')
    expect(recoverZipFilename('README.md')).toBe('README.md')
    expect(recoverZipFilename('config.json')).toBe('config.json')
  })

  it('passes through already-valid UTF-8 CJK unchanged', () => {
    expect(recoverZipFilename('测试')).toBe('测试')
    expect(recoverZipFilename('中文文件名')).toBe('中文文件名')
    expect(recoverZipFilename('项目根目录')).toBe('项目根目录')
  })

  it('passes through empty string unchanged', () => {
    expect(recoverZipFilename('')).toBe('')
  })

  // ── Mixed paths ──

  it('handles mixed ASCII + GBK-Latin1 path segments', () => {
    expect(recoverZipFilename('src/ÖÐÎÄ/index.ts')).toBe('src/中文/index.ts')
    expect(recoverZipFilename('¼òÌåÖÐÎÄ/config.json')).toBe('简体中文/config.json')
  })

  it('handles paths with deep nesting', () => {
    expect(recoverZipFilename('a/b/ÖÐÎÄ/c')).toBe('a/b/中文/c')
  })

  it('preserves full path when segments use same encoding', () => {
    // Real zip files have uniform encoding — all names are GBK or all UTF-8.
    // GBK-Latin1 path: every segment is garbled
    const garbled = '²âÊÔ/ÎÄµµ/ËµÃ÷.txt'
    const recovered = recoverZipFilename(garbled)
    expect(recovered).toBe('测试/文档/说明.txt')
  })

  // ── Edge cases ──

  it('handles strings with only Latin-1 accented chars (no CJK recovery possible)', () => {
    const result = recoverZipFilename('café')
    // No CJK chars in the recovered result → should return as-is
    expect(result).toBe('café')
  })

  it('handles strings that look like Latin-1 but are not GBK', () => {
    // 'À' is C0 in Latin-1, but C0 alone is not valid GBK leading byte
    const result = recoverZipFilename('À')
    expect(result).toBe('À')
  })

  it('is idempotent: running twice gives same result', () => {
    const once = recoverZipFilename('ÖÐÎÄ')
    const twice = recoverZipFilename(once)
    expect(twice).toBe(once)
  })
})
