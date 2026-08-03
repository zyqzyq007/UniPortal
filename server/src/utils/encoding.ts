import iconv from 'iconv-lite'

// Fix garbled filenames caused by UTF-8 bytes misinterpreted as Latin-1.
// Multer's file.originalname can produce mojibake for CJK filenames
// when the Content-Disposition header doesn't use RFC 5987 encoding.
export function recoverUtf8Filename(garbled: string): string {
  if (/[一-鿿]/.test(garbled)) return garbled
  try {
    const buf = Buffer.from(garbled, 'latin1')
    const utf8 = buf.toString('utf8')
    if (/[一-鿿]/.test(utf8)) return utf8
  } catch { /* fall through */ }
  return garbled
}

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
