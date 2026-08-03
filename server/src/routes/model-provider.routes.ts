import { Router } from 'express';
import { authenticateToken } from '../middleware/auth.middleware';
import {
  listProviders,
  createProvider,
  updateProvider,
  deleteProvider,
  testProvider,
  listAvailableModels,
} from '../controllers/model-provider.controller';

const router = Router();
router.use(authenticateToken);

/**
 * @swagger
 * tags:
 *   name: ModelProviders
 *   description: Global model API asset configuration
 */

router.get('/', listProviders);
router.post('/', createProvider);
router.put('/:id', updateProvider);
router.delete('/:id', deleteProvider);
router.post('/:id/test', testProvider);
router.get('/available-models', listAvailableModels);

export default router;
