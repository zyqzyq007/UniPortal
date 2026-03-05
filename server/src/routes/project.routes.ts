import { Router } from 'express';
import multer from 'multer';
import {
  createProject,
  getProjects,
  getProject,
  updateProject,
  deleteProject,
  uploadSoftwareItem,
  getSoftwareItems,
  deleteSoftwareItem,
  downloadSoftwareItem,
  getSoftwareItemStructure,
  getSoftwareItemFileContent,
  operateSoftwareItemNode
} from '../controllers/project.controller';
import { authenticateToken } from '../middleware/auth.middleware';

import fs from 'fs';
import path from 'path';

const router = Router();

// Ensure temp directory exists
const TEMP_DIR = path.join(__dirname, '../../temp_uploads');
if (!fs.existsSync(TEMP_DIR)) {
  fs.mkdirSync(TEMP_DIR, { recursive: true });
}

const upload = multer({
  storage: multer.diskStorage({
    destination: (req, file, cb) => {
      cb(null, TEMP_DIR);
    },
    filename: (req, file, cb) => {
      const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1E9);
      cb(null, file.fieldname + '-' + uniqueSuffix);
    }
  }),
  limits: {
    fileSize: 1024 * 1024 * 1024, // 1GB limit as per requirement
  },
});

// Apply middleware to all routes
router.use(authenticateToken);

// Project Routes
router.post('/', createProject);
router.get('/', getProjects);
router.get('/:id', getProject);
router.put('/:id', updateProject);
router.delete('/:id', deleteProject);

// Software Item Routes
router.post(
  '/:id/items/upload',
  upload.fields([
    { name: 'files', maxCount: 1000 }, // Support folder upload (many files)
    { name: 'archive', maxCount: 1 }   // Support archive upload (single file)
  ]),
  uploadSoftwareItem
);
router.get('/:id/items', getSoftwareItems);
router.delete('/:id/items/:itemId', deleteSoftwareItem);
router.get('/:id/items/:itemId/download', downloadSoftwareItem);
router.get('/:id/items/:itemId/structure', getSoftwareItemStructure);
router.get('/:id/items/:itemId/file', getSoftwareItemFileContent);
router.post('/:id/items/:itemId/fs/node', operateSoftwareItemNode);

export default router;
