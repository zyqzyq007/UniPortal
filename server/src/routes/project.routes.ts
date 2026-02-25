import { Router } from 'express';
import multer from 'multer';
import {
  createProject,
  getProjects,
  getProject,
  updateProject,
  deleteProject,
  getProjectStructure,
  getProjectFileContent,
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
    fileSize: 500 * 1024 * 1024, // 500MB
  },
});

// Apply middleware to all routes
router.use(authenticateToken);

router.post(
  '/',
  upload.fields([
    { name: 'archive', maxCount: 1 },
    { name: 'folder', maxCount: 5000 },
  ]),
  createProject
);
router.get('/', getProjects);
router.get('/:id', getProject);
router.put('/:id', updateProject);
router.delete('/:id', deleteProject);
router.get('/:id/file', getProjectFileContent);
router.get('/:id/structure', getProjectStructure);

export default router;
