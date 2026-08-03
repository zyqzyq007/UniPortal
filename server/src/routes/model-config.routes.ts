import { Router } from 'express';
import { authenticateToken } from '../middleware/auth.middleware';
import { saveModelConfig, getModelConfig, applyModelConfig } from '../controllers/model-config.controller';

const router = Router({ mergeParams: true });
router.use(authenticateToken);

/**
 * @swagger
 * tags:
 *   name: ModelConfig
 *   description: Project-level model configuration and RAG apply
 */

// GET  /api/projects/:id/model-config         — get current selection
// PUT  /api/projects/:id/model-config         — save selection
// POST /api/projects/:id/model-config/apply   — write env + restart RAG + reindex
router.get('/', getModelConfig);
router.put('/', saveModelConfig);
router.post('/apply', applyModelConfig);

export default router;
