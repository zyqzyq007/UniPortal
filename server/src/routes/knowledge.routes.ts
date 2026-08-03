import { Router } from 'express';
import multer from 'multer';
import path from 'path';
import fs from 'fs';
import {
  uploadDocument,
  listDocuments,
  deleteDocument,
  previewDocument,
  downloadDocument,
  reindexDocument,
  retrieval,
  denseRetrieval,
  sparseRetrieval,
} from '../controllers/knowledge.controller';
import { authenticateToken } from '../middleware/auth.middleware';

const router = Router();

const TEMP_DIR = path.join(__dirname, '../../temp_uploads');
if (!fs.existsSync(TEMP_DIR)) {
  fs.mkdirSync(TEMP_DIR, { recursive: true });
}

const upload = multer({
  storage: multer.diskStorage({
    destination: (_req, _file, cb) => cb(null, TEMP_DIR),
    filename: (_req, file, cb) => {
      const suffix = Date.now() + '-' + Math.round(Math.random() * 1e9);
      cb(null, file.fieldname + '-' + suffix);
    },
  }),
  limits: { fileSize: 50 * 1024 * 1024 }, // 50MB per document
});

router.use(authenticateToken);

/**
 * @swagger
 * tags:
 *   name: Knowledge
 *   description: Knowledge base & RAG retrieval API
 */

/**
 * @swagger
 * /knowledge/{projectId}/documents:
 *   post:
 *     summary: Upload document to knowledge base
 *     tags: [Knowledge]
 *     security: [{ bearerAuth: [] }]
 *     parameters:
 *       - in: path
 *         name: projectId
 *         required: true
 *         schema: { type: string }
 *     requestBody:
 *       required: true
 *       content:
 *         multipart/form-data:
 *           schema:
 *             type: object
 *             properties:
 *               file: { type: string, format: binary }
 *     responses:
 *       201: { description: Document uploaded and indexed }
 *       400: { description: No file uploaded }
 *       503: { description: RAG service unavailable }
 */
router.post('/:projectId/documents', upload.single('file'), uploadDocument);

/**
 * @swagger
 * /knowledge/{projectId}/documents:
 *   get:
 *     summary: List knowledge base documents for a project
 *     tags: [Knowledge]
 *     security: [{ bearerAuth: [] }]
 *     parameters:
 *       - in: path
 *         name: projectId
 *         required: true
 *         schema: { type: string }
 *     responses:
 *       200: { description: Document list }
 */
router.get('/:projectId/documents', listDocuments);

/**
 * @swagger
 * /knowledge/{projectId}/documents/{documentId}:
 *   delete:
 *     summary: Delete document from knowledge base
 *     tags: [Knowledge]
 *     security: [{ bearerAuth: [] }]
 *     parameters:
 *       - in: path
 *         name: projectId
 *         required: true
 *         schema: { type: string }
 *       - in: path
 *         name: documentId
 *         required: true
 *         schema: { type: string }
 *     responses:
 *       200: { description: Document deleted }
 *       404: { description: Document not found }
 */
router.delete('/:projectId/documents/:documentId', deleteDocument);
router.get('/:projectId/documents/:documentId/preview', previewDocument);
router.get('/:projectId/documents/:documentId/download', downloadDocument);
router.post('/:projectId/documents/:documentId/reindex', reindexDocument);

/**
 * @swagger
 * /knowledge/{projectId}/retrieval:
 *   post:
 *     summary: Hybrid retrieval (dense + sparse) for sub-tools
 *     tags: [Knowledge]
 *     security: [{ bearerAuth: [] }]
 *     parameters:
 *       - in: path
 *         name: projectId
 *         required: true
 *         schema: { type: string }
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             properties:
 *               query: { type: string }
 *               top_k: { type: integer }
 *     responses:
 *       200: { description: Retrieval results }
 */
router.post('/:projectId/retrieval', retrieval);

/**
 * @swagger
 * /knowledge/{projectId}/retrieval/dense:
 *   post:
 *     summary: Dense-only retrieval
 *     tags: [Knowledge]
 *     security: [{ bearerAuth: [] }]
 *     parameters:
 *       - in: path
 *         name: projectId
 *         required: true
 *         schema: { type: string }
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             properties:
 *               query: { type: string }
 *               top_k: { type: integer }
 *     responses:
 *       200: { description: Dense retrieval results }
 */
router.post('/:projectId/retrieval/dense', denseRetrieval);

/**
 * @swagger
 * /knowledge/{projectId}/retrieval/sparse:
 *   post:
 *     summary: Sparse-only (BM25) retrieval
 *     tags: [Knowledge]
 *     security: [{ bearerAuth: [] }]
 *     parameters:
 *       - in: path
 *         name: projectId
 *         required: true
 *         schema: { type: string }
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             properties:
 *               query: { type: string }
 *               top_k: { type: integer }
 *     responses:
 *       200: { description: Sparse retrieval results }
 */
router.post('/:projectId/retrieval/sparse', sparseRetrieval);

export default router;
