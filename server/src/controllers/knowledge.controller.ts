import { Response } from 'express';
import { readFileSync, writeFileSync, unlinkSync, existsSync, mkdirSync } from 'fs';
import path from 'path';
import mammoth from 'mammoth';
import prisma from '../prisma';
import { AuthRequest } from '../middleware/auth.middleware';
import { recoverUtf8Filename } from '../utils/encoding';

const KNOWLEDGE_PREVIEW_ROOT = path.join(__dirname, '../../storage');

// Node 20+ globals not typed in ES2020 target
declare class Blob {
  constructor(parts: any[], options?: { type?: string });
}
declare class FormData {
  append(name: string, value: any, filename?: string): void;
}

const RAG_SERVICE_URL = process.env.RAG_SERVICE_URL || 'http://localhost:8001';

// RAG API response types
interface RAGDocument {
  id: string;
  filename: string;
  status: string;
  chunks?: number;  // RAG API field name
  created_at?: string;
  error?: string;
  size_bytes?: number;
}

function humanStatus(rag: RAGDocument | undefined, filename: string, allDocs: RAGDocument[]): string {
  // RAG doc not in list yet — file was just uploaded, still registering
  if (!rag) return '处理中';
  if (rag.status === 'indexed') return '已索引';
  if (rag.status === 'processing') return '处理中';
  // failed — diagnose the most likely cause
  const ext = filename.split('.').pop()?.toLowerCase();

  // If ALL documents failed, it's almost certainly an embedding/API-key issue
  const anyIndexed = allDocs.some((d) => d.status === 'indexed');
  if (!anyIndexed && allDocs.length > 0) {
    return '嵌入服务未配置(DASHSCOPE_API_KEY)，无法生成向量索引。';
  }

  // Some docs indexed but this one failed — per-file diagnosis
  if (ext === 'pdf') {
    return 'PDF解析失败：该文件可能是扫描件或纯图片，无文字层。请使用含文字层的PDF，或对扫描件做OCR。';
  }
  return '文档处理失败，请查看RAG服务日志排查具体原因。';
}

interface RAGRetrievedDocument {
  content: string;
  source?: string;        // top-level filename from RAG
  title?: string;
  metadata?: Record<string, any>;
  score: number;
  retrieval_score?: number;
  rerank_score?: number;
  rerank_applied?: boolean;
}

interface RAGUploadResponse {
  id: string;
  filename: string;
  status: string;
  message?: string;
}

interface RAGListResponse {
  documents: RAGDocument[];
  total: number;
}

interface RAGRetrievalResponse {
  query: string;
  results: RAGRetrievedDocument[];
  total: number;
  retrieval_time_ms: number;
}

// Upload document to RAG and record in Prisma
export const uploadDocument = async (req: AuthRequest, res: Response) => {
  try {
    const { projectId } = req.params;
    const file = req.file;
    if (!file) {
      return res.status(400).json({ code: 400, message: 'No file uploaded' });
    }

    // Verify project exists and user has access
    const project = await prisma.testProject.findFirst({
      where: { project_id: projectId, owner_id: req.user!.id },
    });
    if (!project) {
      cleanupTempFile(file.path);
      return res.status(404).json({ code: 404, message: 'Project not found' });
    }

    const originalName = recoverUtf8Filename(file.originalname);

    // Forward file to RAG service
    const fileBuffer = readFileSync(file.path);
    const blob = new Blob([fileBuffer], { type: file.mimetype || 'application/octet-stream' });
    const formData = new FormData();
    formData.append('file', blob, originalName);

    const ragResponse = await fetch(`${RAG_SERVICE_URL}/api/documents/upload`, {
      method: 'POST',
      body: formData as unknown as BodyInit,
    });

    if (!ragResponse.ok) {
      const errBody = await ragResponse.text();
      cleanupTempFile(file.path);
      return res.status(ragResponse.status).json({
        code: ragResponse.status,
        message: `RAG service error: ${errBody}`,
      });
    }

    const ragResult: RAGUploadResponse = await ragResponse.json();

    // Record in Prisma
    const record = await prisma.knowledgeDocument.create({
      data: {
        project_id: projectId,
        rag_document_id: ragResult.id,
        filename: originalName,
        file_size: BigInt(file.size),
        uploaded_by: req.user!.id,
      },
    });

    // Save a copy for preview (best-effort, don't fail upload on it)
    try {
      const previewDir = path.join(KNOWLEDGE_PREVIEW_ROOT, projectId, 'knowledge', record.id);
      mkdirSync(previewDir, { recursive: true });
      writeFileSync(path.join(previewDir, originalName), fileBuffer);
    } catch (e) {
      console.warn(`Failed to save preview copy for ${record.id}:`, e);
    } finally {
      cleanupTempFile(file.path);
    }

    return res.status(201).json({
      code: 201,
      data: {
        id: record.id,
        rag_document_id: ragResult.id,
        filename: record.filename,
        status: ragResult.status,
        file_size: file.size,
        created_at: record.created_at,
      },
    });
  } catch (error: any) {
    const cause = error?.cause?.code || error?.cause?.errno;
    if (cause === 'ECONNREFUSED' || cause === 'ENOTFOUND' || cause === 'EAI_AGAIN') {
      return res.status(503).json({ code: 503, message: 'RAG service unavailable' });
    }
    console.error('uploadDocument error:', error);
    return res.status(500).json({ code: 500, message: 'Internal server error' });
  }
};

// List documents for a project
export const listDocuments = async (req: AuthRequest, res: Response) => {
  try {
    const { projectId } = req.params;

    const documents = await prisma.knowledgeDocument.findMany({
      where: { project_id: projectId },
      orderBy: { created_at: 'desc' },
    });

    // Try to enrich with RAG status, but don't fail if RAG is down
    let ragDocs: RAGDocument[] = [];
    try {
      const ragResponse = await fetch(`${RAG_SERVICE_URL}/api/documents`);
      if (ragResponse.ok) {
        const ragResult: RAGListResponse = await ragResponse.json();
        ragDocs = ragResult.documents;
      }
    } catch {
      // RAG unavailable, return basic info
    }

    const ragDocMap = new Map(ragDocs.map((d: RAGDocument) => [d.id, d]));

    const enriched = documents.map((d) => {
      const rag = ragDocMap.get(d.rag_document_id);
      // If RAG doc not found yet, treat as 'processing' (just uploaded, registering)
      const status = rag?.status || 'processing';
      return {
        id: d.id,
        rag_document_id: d.rag_document_id,
        filename: d.filename,
        file_size: d.file_size.toString(),
        uploaded_by: d.uploaded_by,
        created_at: d.created_at,
        status,
        status_label: humanStatus(rag, d.filename, ragDocs),
        chunk_count: rag?.chunks ?? 0,
      };
    });

    return res.status(200).json({
      code: 200,
      data: { documents: enriched, total: enriched.length },
    });
  } catch (error) {
    console.error('listDocuments error:', error);
    return res.status(500).json({ code: 500, message: 'Internal server error' });
  }
};

// Delete document from RAG and Prisma
export const deleteDocument = async (req: AuthRequest, res: Response) => {
  try {
    const { projectId, documentId } = req.params;

    const doc = await prisma.knowledgeDocument.findFirst({
      where: { id: documentId, project_id: projectId },
    });
    if (!doc) {
      return res.status(404).json({ code: 404, message: 'Document not found' });
    }

    // Delete from RAG service (best-effort)
    try {
      await fetch(`${RAG_SERVICE_URL}/api/documents/${doc.rag_document_id}`, {
        method: 'DELETE',
      });
    } catch {
      console.warn(`Failed to delete RAG document ${doc.rag_document_id}, removing local record anyway`);
    }

    await prisma.knowledgeDocument.delete({ where: { id: documentId } });

    return res.status(200).json({ code: 200, message: 'Document deleted' });
  } catch (error) {
    console.error('deleteDocument error:', error);
    return res.status(500).json({ code: 500, message: 'Internal server error' });
  }
};

// Sanitize top_k: must be a positive integer in [1, 50]
function sanitizeTopK(raw: any): number {
  const n = typeof raw === 'number' ? raw : parseInt(raw, 10);
  if (!Number.isFinite(n) || n <= 0 || !Number.isInteger(n)) return 5;
  return Math.min(Math.max(n, 1), 50);
}

// Sanitize confidence threshold: float in [0, 1], default 0.3
function sanitizeThreshold(raw: any): number {
  if (typeof raw !== 'number' || !Number.isFinite(raw) || raw < 0 || raw > 1) return 0.3;
  return raw;
}

// Best relevance score: prefer rerank (cross-encoder) > retrieval_score > raw score
function pickScore(r: RAGRetrievedDocument): number {
  if (r.rerank_applied && typeof r.rerank_score === 'number') return r.rerank_score;
  return r.retrieval_score ?? r.score;
}

// Shared post-processing: project filter → target docs → normalize (sparse) → threshold → sort → slice
function postProcess(
  ragResult: RAGRetrievalResponse,
  projectFilenames: Set<string>,
  targetDocs: Set<string> | null,
  threshold: number,
  top_k: number,
  mode: 'hybrid' | 'dense' | 'sparse'
) {
  // 1. Filter by project's known filenames
  let filtered = ragResult.results.filter((r) => {
    const src = r.source || r.metadata?.filename || r.metadata?.source || '';
    return projectFilenames.has(src);
  });

  // 2. Filter by target docs if specified
  if (targetDocs && targetDocs.size > 0) {
    filtered = filtered.filter((r) => {
      const src = r.source || r.metadata?.filename || r.metadata?.source || '';
      return targetDocs.has(src);
    });
  }

  // 3. Fall back to unfiltered if project filter removed everything (race condition)
  const pool = filtered.length > 0 ? filtered : ragResult.results;

  // 4. For sparse (BM25) mode: normalize scores to [0, 1] by dividing by max.
  //    BM25 scores are unbounded — without normalization, threshold has no meaning.
  let working = pool;
  if (mode === 'sparse' && pool.length > 0) {
    const maxScore = Math.max(...pool.map((r) => pickScore(r)));
    if (maxScore > 1) {
      working = pool.map((r) => {
        const normalized = pickScore(r) / maxScore;
        // Overwrite score with normalized value; clear retrieval_score so
        // pickScore falls through to the normalized `score`.
        const { retrieval_score, ...rest } = r;
        return { ...rest, score: normalized };
      });
    }
  }

  // 5. Apply confidence threshold
  const aboveThreshold = working.filter((r) => pickScore(r) >= threshold);

  // 6. Sort by score descending
  aboveThreshold.sort((a, b) => pickScore(b) - pickScore(a));

  // 7. Slice to top_k
  const results = aboveThreshold.slice(0, top_k);

  return {
    query: ragResult.query,
    results,
    matched_count: aboveThreshold.length,
    returned_count: results.length,
    threshold,
    total: results.length,
    retrieval_time_ms: ragResult.retrieval_time_ms,
  };
}

// Hybrid retrieval (dense + sparse) with project-scoped post-filtering
export const retrieval = async (req: AuthRequest, res: Response) => {
  try {
    const { projectId } = req.params;
    const { query, documents: targetDocsRaw } = req.body;
    const top_k = sanitizeTopK(req.body.top_k);
    const threshold = sanitizeThreshold(req.body.threshold);

    if (!query || typeof query !== 'string') {
      return res.status(400).json({ code: 400, message: 'Query string is required' });
    }

    // Optional: target document filter (array of filenames). Empty/invalid → search all
    const targetDocs = Array.isArray(targetDocsRaw)
      ? new Set(targetDocsRaw.filter((d: any) => typeof d === 'string'))
      : null;

    // Get known document IDs for this project
    const projectDocs = await prisma.knowledgeDocument.findMany({
      where: { project_id: projectId },
      select: { rag_document_id: true, filename: true },
    });
    const projectFilenames = new Set(projectDocs.map((d) => d.filename));

    // Fetch from RAG with larger top_k for post-filtering
    const fetchTopK = Math.max(top_k * 4, 20);
    const ragResponse = await fetch(`${RAG_SERVICE_URL}/api/retrieval`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, top_k: fetchTopK }),
    });

    if (!ragResponse.ok) {
      const errBody = await ragResponse.text();
      return res.status(ragResponse.status).json({
        code: ragResponse.status,
        message: `RAG retrieval error: ${errBody}`,
      });
    }

    const ragResult: RAGRetrievalResponse = await ragResponse.json();

    const data = postProcess(ragResult, projectFilenames, targetDocs, threshold, top_k, 'hybrid');

    return res.status(200).json({ code: 200, data });
  } catch (error: any) {
    const cause = error?.cause?.code || error?.cause?.errno;
    if (cause === 'ECONNREFUSED' || cause === 'ENOTFOUND' || cause === 'EAI_AGAIN') {
      return res.status(503).json({ code: 503, message: 'RAG service unavailable' });
    }
    console.error('retrieval error:', error);
    return res.status(500).json({ code: 500, message: 'Internal server error' });
  }
};

// Helper: run a single-mode retrieval (dense/sparse) with full post-processing
async function singleModeRetrieval(
  req: AuthRequest,
  res: Response,
  endpoint: 'dense' | 'sparse'
) {
  try {
    const { projectId } = req.params;
    const { query, documents: targetDocsRaw } = req.body;
    const top_k = sanitizeTopK(req.body.top_k);
    const threshold = sanitizeThreshold(req.body.threshold);

    if (!query || typeof query !== 'string') {
      return res.status(400).json({ code: 400, message: 'Query string is required' });
    }

    const targetDocs = Array.isArray(targetDocsRaw)
      ? new Set(targetDocsRaw.filter((d: any) => typeof d === 'string'))
      : null;

    const projectDocs = await prisma.knowledgeDocument.findMany({
      where: { project_id: projectId },
      select: { rag_document_id: true, filename: true },
    });
    const projectFilenames = new Set(projectDocs.map((d) => d.filename));

    const fetchTopK = Math.max(top_k * 4, 20);
    const ragResponse = await fetch(`${RAG_SERVICE_URL}/api/retrieval/${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, top_k: fetchTopK }),
    });

    if (!ragResponse.ok) {
      return res.status(ragResponse.status).json({
        code: ragResponse.status,
        message: `RAG ${endpoint} retrieval error`,
      });
    }

    const ragResult: RAGRetrievalResponse = await ragResponse.json();
    const data = postProcess(ragResult, projectFilenames, targetDocs, threshold, top_k, endpoint);
    return res.status(200).json({ code: 200, data });
  } catch (error: any) {
    const cause = error?.cause?.code || error?.cause?.errno;
    if (cause === 'ECONNREFUSED' || cause === 'ENOTFOUND' || cause === 'EAI_AGAIN') {
      return res.status(503).json({ code: 503, message: 'RAG service unavailable' });
    }
    console.error(`${endpoint}Retrieval error:`, error);
    return res.status(500).json({ code: 500, message: 'Internal server error' });
  }
}

// Dense-only retrieval variant
export const denseRetrieval = (req: AuthRequest, res: Response) => singleModeRetrieval(req, res, 'dense');

// Sparse-only retrieval variant
export const sparseRetrieval = (req: AuthRequest, res: Response) => singleModeRetrieval(req, res, 'sparse');

function cleanupTempFile(filePath: string) {
  try {
    if (filePath && existsSync(filePath)) {
      unlinkSync(filePath);
    }
  } catch {
    // Best effort cleanup
  }
}

// Preview/download document — returns raw file content
export const previewDocument = async (req: AuthRequest, res: Response) => {
  try {
    const { projectId, documentId } = req.params;
    const doc = await prisma.knowledgeDocument.findFirst({
      where: { id: documentId, project_id: projectId },
    });
    if (!doc) {
      return res.status(404).json({ code: 404, message: 'Document not found' });
    }

    const filePath = path.join(KNOWLEDGE_PREVIEW_ROOT, projectId, 'knowledge', documentId, doc.filename);
    if (!existsSync(filePath)) {
      return res.status(404).json({
        code: 404,
        message: '该文档暂无预览副本。可能是在预览功能上线前上传的。删除后重新上传即可启用预览。',
      });
    }

    const ext = doc.filename.split('.').pop()?.toLowerCase() || '';

    // Text-based formats — return raw content
    const textExts = ['txt', 'md', 'markdown', 'json', 'csv', 'log', 'yml', 'yaml', 'xml', 'html', 'htm', 'py', 'js', 'ts', 'java', 'c', 'cpp', 'go', 'rs', 'sh'];
    if (textExts.includes(ext)) {
      const content = readFileSync(filePath, 'utf-8');
      return res.status(200).json({
        code: 200,
        data: { filename: doc.filename, content, type: 'text', size: content.length },
      });
    }

    // DOCX — convert to HTML preserving formatting (headings, bold, lists)
    if (ext === 'docx') {
      try {
        const buffer = readFileSync(filePath);
        const result = await mammoth.convertToHtml({ buffer });
        return res.status(200).json({
          code: 200,
          data: {
            filename: doc.filename,
            content: result.value || '<p>(空文档)</p>',
            type: 'html',
            size: result.value?.length || 0,
          },
        });
      } catch (e: any) {
        return res.status(200).json({
          code: 200,
          data: {
            filename: doc.filename,
            type: 'binary',
            ext,
            download_url: `/api/knowledge/${projectId}/documents/${documentId}/download`,
          },
        });
      }
    }

    // Images — return base64 for inline display
    const imageExts = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'];
    if (imageExts.includes(ext)) {
      const buffer = readFileSync(filePath);
      const base64 = buffer.toString('base64');
      const mimeMap: Record<string, string> = {
        png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg',
        gif: 'image/gif', webp: 'image/webp', svg: 'image/svg+xml', bmp: 'image/bmp',
      };
      return res.status(200).json({
        code: 200,
        data: {
          filename: doc.filename,
          type: 'image',
          src: `data:${mimeMap[ext] || 'image/png'};base64,${base64}`,
        },
      });
    }

    // PDF — iframe via download URL
    if (ext === 'pdf') {
      return res.status(200).json({
        code: 200,
        data: {
          filename: doc.filename,
          type: 'pdf',
          ext,
          download_url: `/api/knowledge/${projectId}/documents/${documentId}/download`,
        },
      });
    }

    // Other binary formats (doc, pptx, etc) — download link
    return res.status(200).json({
      code: 200,
      data: {
        filename: doc.filename,
        type: 'binary',
        ext,
        download_url: `/api/knowledge/${projectId}/documents/${documentId}/download`,
      },
    });
  } catch (error) {
    console.error('previewDocument error:', error);
    return res.status(500).json({ code: 500, message: 'Internal server error' });
  }
};

// Download raw document file (supports inline for preview)
export const downloadDocument = async (req: AuthRequest, res: Response) => {
  try {
    const { projectId, documentId } = req.params;
    const doc = await prisma.knowledgeDocument.findFirst({
      where: { id: documentId, project_id: projectId },
    });
    if (!doc) {
      return res.status(404).json({ code: 404, message: 'Document not found' });
    }

    const filePath = path.join(KNOWLEDGE_PREVIEW_ROOT, projectId, 'knowledge', documentId, doc.filename);
    if (!existsSync(filePath)) {
      return res.status(404).json({ code: 404, message: 'File not available' });
    }

    const mode = (req.query.mode as string) || 'attachment';
    // Use ASCII-safe filename in header to prevent Express crash on Chinese chars
    const asciiName = doc.filename.replace(/[^\x20-\x7E]/g, '_');
    if (mode === 'inline') {
      return res.sendFile(filePath, {
        headers: {
          'Content-Disposition': `inline; filename="${asciiName}"`,
          'Content-Type': 'application/pdf',
        },
      });
    }
    return res.download(filePath, asciiName);
  } catch (error) {
    console.error('downloadDocument error:', error);
    return res.status(500).json({ code: 500, message: 'Internal server error' });
  }
};

// Reindex a document — delete from RAG and re-upload to force fresh indexing.
// (RAG only supports bulk reindex, so we emulate per-doc reindex via delete + re-upload.)
export const reindexDocument = async (req: AuthRequest, res: Response) => {
  try {
    const { projectId, documentId } = req.params;
    const doc = await prisma.knowledgeDocument.findFirst({
      where: { id: documentId, project_id: projectId },
    });
    if (!doc) {
      return res.status(404).json({ code: 404, message: 'Document not found' });
    }

    // Find the locally saved preview file
    const filePath = path.join(KNOWLEDGE_PREVIEW_ROOT, projectId, 'knowledge', documentId, doc.filename);
    if (!existsSync(filePath)) {
      return res.status(404).json({
        code: 404,
        message: '无法重建索引：本地文件副本不存在（可能在上传预览功能上线前上传）',
      });
    }

    // 1. Delete old RAG document
    try {
      await fetch(`${RAG_SERVICE_URL}/api/documents/${doc.rag_document_id}`, { method: 'DELETE' });
    } catch { /* best effort */ }

    // 1b. Poll until RAG confirms the document is fully removed (dedup hash cleared)
    let fullyDeleted = false;
    for (let i = 0; i < 10; i++) {
      await new Promise((r) => setTimeout(r, 500));
      try {
        const check = await fetch(`${RAG_SERVICE_URL}/api/documents/${doc.rag_document_id}`);
        if (check.status === 404) { fullyDeleted = true; break; }
      } catch { /* retry */ }
    }
    if (!fullyDeleted) {
      // Even if not confirmed, try calling dedup cleanup
      try {
        await fetch(`${RAG_SERVICE_URL}/api/documents/dedup`, { method: 'POST' });
        await new Promise((r) => setTimeout(r, 1000));
      } catch { /* best effort */ }
    }

    // 2. Re-upload to RAG
    const fileBuffer = readFileSync(filePath);
    const blob = new Blob([fileBuffer], { type: 'application/octet-stream' });
    const formData = new FormData();
    formData.append('file', blob, doc.filename);

    const ragResponse = await fetch(`${RAG_SERVICE_URL}/api/documents/upload`, {
      method: 'POST',
      body: formData as unknown as BodyInit,
    });

    if (!ragResponse.ok) {
      const errBody = await ragResponse.text();
      // If still dedup-blocked, return a clear message
      if (errBody.includes('已上传过') || errBody.includes('duplicate')) {
        return res.status(409).json({
          code: 409,
          message: 'RAG 去重缓存未清理完成，请稍后重试',
        });
      }
      return res.status(ragResponse.status).json({
        code: ragResponse.status,
        message: `RAG re-upload error: ${errBody}`,
      });
    }

    const ragResult: RAGUploadResponse = await ragResponse.json();

    // 3. Update Prisma record with new rag_document_id
    await prisma.knowledgeDocument.update({
      where: { id: documentId },
      data: { rag_document_id: ragResult.id },
    });

    return res.status(200).json({
      code: 200,
      data: {
        document_id: documentId,
        rag_document_id: ragResult.id,
        status: 'processing',
        message: '重建索引已启动',
      },
    });
  } catch (error: any) {
    const cause = error?.cause?.code || error?.cause?.errno;
    if (cause === 'ECONNREFUSED' || cause === 'ENOTFOUND' || cause === 'EAI_AGAIN') {
      return res.status(503).json({ code: 503, message: 'RAG service unavailable' });
    }
    console.error('reindexDocument error:', error);
    return res.status(500).json({ code: 500, message: 'Internal server error' });
  }
};
