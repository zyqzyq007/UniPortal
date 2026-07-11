import iconv from 'iconv-lite'

// Fix garbled filenames caused by GBK-encoded zip entries.
// Zip files created on Chinese Windows often encode filenames in GBK
// but adm-zip interprets the bytes as Latin-1, producing mojibake.
// This function tries to reverse the mangling.
export function recoverZipFilename(garbled: string): string {
  if (/[一-龥]/.test(garbled)) return garbled
  try {
    const buf = Buffer.from(garbled, 'latin1')
    const gbk = iconv.decode(buf, 'gbk')
    if (/[一-龥]/.test(gbk)) return gbk
    const gb2312 = iconv.decode(buf, 'gb2312')
    if (/[一-龥]/.test(gb2312)) return gb2312
  } catch { /* fall through */ }
  return garbled
}
