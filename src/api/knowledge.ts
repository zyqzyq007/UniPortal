import request from '../utils/request';

export interface KnowledgeDocument {
  id: string;
  rag_document_id: string;
  filename: string;
  file_size: string;
  uploaded_by: string;
  created_at: string;
  status?: string;
  status_label?: string;
  chunk_count?: number;
}

export interface RetrievalResult {
  content: string;
  source?: string;
  title?: string;
  metadata?: Record<string, any>;
  score: number;
  retrieval_score?: number;
  rerank_score?: number;
  rerank_applied?: boolean;
}

export interface RetrievalResponse {
  query: string;
  results: RetrievalResult[];
  matched_count: number;
  returned_count: number;
  threshold: number;
  total: number;
  retrieval_time_ms: number;
}

export const uploadDocument = (projectId: string, formData: FormData): Promise<{ code: number; data: KnowledgeDocument }> => {
  return request({
    url: `/knowledge/${projectId}/documents`,
    method: 'post',
    data: formData,
  });
};

export const getDocuments = (projectId: string): Promise<{ code: number; data: { documents: KnowledgeDocument[]; total: number } }> => {
  return request({
    url: `/knowledge/${projectId}/documents`,
    method: 'get',
  });
};

export const deleteDocument = (projectId: string, documentId: string): Promise<{ code: number; message: string }> => {
  return request({
    url: `/knowledge/${projectId}/documents/${documentId}`,
    method: 'delete',
  });
};

export interface PreviewResponse {
  filename: string;
  content?: string;
  type: 'text' | 'html' | 'binary' | 'image' | 'pdf';
  size?: number;
  ext?: string;
  src?: string;         // base64 data URL for images
  download_url?: string;
}

export const previewDocument = (projectId: string, documentId: string): Promise<{ code: number; data: PreviewResponse }> => {
  return request({
    url: `/knowledge/${projectId}/documents/${documentId}/preview`,
    method: 'get',
  });
};

export const downloadDocumentUrl = (projectId: string, documentId: string): string => {
  return `/api/knowledge/${projectId}/documents/${documentId}/download`;
};

export const reindexDocument = (projectId: string, documentId: string): Promise<{ code: number; data: { status: string; message?: string } }> => {
  return request({
    url: `/knowledge/${projectId}/documents/${documentId}/reindex`,
    method: 'post',
  });
};

export type RetrievalMode = 'hybrid' | 'dense' | 'sparse';

export const retrieval = (
  projectId: string,
  query: string,
  topK: number = 5,
  mode: RetrievalMode = 'hybrid',
  documents?: string[],
  threshold: number = 0.3
): Promise<{ code: number; data: RetrievalResponse }> => {
  const suffix = mode === 'hybrid' ? '' : `/${mode}`;
  return request({
    url: `/knowledge/${projectId}/retrieval${suffix}`,
    method: 'post',
    data: { query, top_k: topK, documents, threshold },
  });
};
