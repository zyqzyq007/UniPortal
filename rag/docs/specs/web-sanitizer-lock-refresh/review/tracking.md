# Tracking — Web Sanitizer Lock Refresh

## 追踪矩阵

| Finding | Severity | REQ | Defender | Design | Fix commit | Verification | Permanent regression | Status |
|---|---|---|---|---|---|---|---|---|
| F-01 | Critical | REQ-WSR-005 | accepted | v2 §3/§5 | `31fcabb` | final cold web-builder/full image；DOMPurify 3.4.12 | Docker contract + final runs | closed |
| F-02 | High | REQ-WSR-004 | accepted | v2.1 §5 | `31fcabb`,`b0a559b` | normal/failure DOM assertions；remote 24-PNG artifact reviewed | sanitizer Playwright + artifact contract | closed |
| F-03 | High | REQ-WSR-007 | accepted | v2 §6 | `31fcabb` | lock rejects `<3.4.11`；forward-only rollback | `test_dompurify_lock_is_patched_and_has_trusted_provenance` | closed |
| F-04 | High | REQ-WSR-006 | accepted | v2 §1/§4 | `31fcabb` | official registry audit 0；HTTPS + sha512 | lock/audit contracts | closed |
| F-05 | High | REQ-WSR-001..006 | accepted | v2.1 §5/tasks | `31fcabb`,`b4c0f56`,`b0a559b` | 红→绿、24 contracts、21 browser、final warm/cold | unit + Playwright permanent regressions | closed |
| WSR-IMP-H-01 | High | REQ-WSR-004 | accepted | v2.1 §4/§5 | `31fcabb` | forced sanitizer error → escaped fallback | fallback contract + Playwright fail-closed | closed |
| WSR-IMP-M-01 | Medium | REQ-WSR-005/006 | accepted | v2.1 §1/§3 | `31fcabb` | hosted/Docker Node 20.20.2 / npm 10.8.2 | toolchain contracts | closed |
| WSR-IMP-M-02 | Medium | REQ-WSR-002/005 | defended-with-alternative | v2.1 §2/§3 | `31fcabb` | npm metadata normalization + Debian/glibc builder | lock tuple audit + cold Docker | closed |
| DLV-H-01 | High | REQ-WSR-003/004 | accepted | delivery review | `b0a559b` | mass-delete mutation red；sentinel 保留 | session delete Playwright | closed |
| DLV-M-02 | Medium | REQ-WSR-003/004 | accepted | delivery review | `b0a559b` | artifact `8369549208` 下载并目检；trace retained | workflow/config contracts | closed |

## Local Evidence

- Node 20.20.2 / npm 10.8.2 lock refresh from `https://registry.npmjs.org/` with empty userconfig.
- Package tuple audit: only DOMPurify 3.4.7→3.4.12 and its direct trusted-types layout changed;
  unrelated version/resolved/integrity tuples stayed fixed. npm 10.8.2 additionally normalized the Rollup GNU
  entry by removing its redundant `libc` metadata; the production builder is pinned to Debian/glibc.
- `npm audit --omit=dev`: 0 production vulnerabilities.
- cold classic Docker: web-builder 29s; full build 106s; Python dependency sync 40s;
  image 478101058 bytes; no FlagEmbedding/torch/ST/transformers/langchain-huggingface; import and
  versioned domain-profile files verified.
- Playwright: 21 passed; reviewer inspected sanitizer-safe-output, sanitizer-failure-fallback,
  sources-panel and opened-session.

最终代码 SHA 为 `b0a559b`。F-01..F-05 与 implementation/delivery findings 已全部关闭；远程
Docker/Playwright 指标、run URL、artifact digest 与人工截图检查记录见
[delivery evidence](../../ci-index-routing/review/delivery-evidence.md)。
