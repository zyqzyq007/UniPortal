import { Request, Response } from 'express';
import path from 'path';
import fs from 'fs';
import prisma from '../prisma';
import { Prisma } from '@prisma/client';
import { AuthRequest } from '../middleware/auth.middleware';
import { StructureService } from '../services/structure.service';

const STORAGE_ROOT = path.join(__dirname, '../../storage');

// Ensure storage root exists
if (!fs.existsSync(STORAGE_ROOT)) {
  fs.mkdirSync(STORAGE_ROOT, { recursive: true });
}

export const createProject = async (req: AuthRequest, res: Response) => {
  try {
    const { name, description, repoUrl } = req.body;
    if (!req.user) {
      return res.status(401).json({ code: 401, message: 'Unauthorized' });
    }
    const userId = req.user.id;

    if (!name) {
      return res.status(400).json({ code: 400, message: 'Project name is required' });
    }

    const files = req.files as Record<string, Express.Multer.File[]> | undefined;
    const archiveFiles = files?.archive || [];
    const folderFiles = files?.folder || [];
    const hasRepo = !!repoUrl && String(repoUrl).trim().length > 0;
    const hasArchive = archiveFiles.length > 0;
    const hasFolder = folderFiles.length > 0;
    const sourcesCount = [hasRepo, hasArchive, hasFolder].filter(Boolean).length;
    if (sourcesCount !== 1) {
      return res.status(400).json({
        code: 400,
        message: 'Invalid upload source',
        detail: 'Provide exactly one of repoUrl, archive, or folder',
      });
    }

    const project = await prisma.project.create({
      data: {
        name,
        description,
        owner: {
          connect: { id: userId },
        },
      },
    });

    const projectPath = path.join(STORAGE_ROOT, project.project_id);
    if (!fs.existsSync(projectPath)) {
      fs.mkdirSync(projectPath, { recursive: true });
      fs.writeFileSync(path.join(projectPath, 'package.json'), JSON.stringify({ name, version: '1.0.0' }, null, 2));
    }

    if (hasArchive) {
      const file = archiveFiles[0];
      const targetPath = path.resolve(projectPath, file.originalname);
      if (!targetPath.startsWith(projectPath)) {
        // Clean up temp file
        if (file.path) fs.unlinkSync(file.path);
        return res.status(400).json({ code: 400, message: 'Invalid file path' });
      }
      // Move file from temp to target
      fs.renameSync(file.path, targetPath);
    }

    if (hasFolder) {
      const folderPaths = req.body.folderPaths; // string | string[]
      
      for (let i = 0; i < folderFiles.length; i++) {
        const file = folderFiles[i];
        let relativePath = file.originalname;
        
        // Use explicit path if available
        if (folderPaths) {
          if (Array.isArray(folderPaths)) {
            // Ensure index bounds and use the corresponding path
            if (i < folderPaths.length) relativePath = folderPaths[i] as string;
          } else if (typeof folderPaths === 'string' && folderFiles.length === 1) {
            relativePath = folderPaths;
          }
        }
        
        // Fallback to filename if relativePath is empty or just filename
        relativePath = relativePath || file.filename;

        const targetPath = path.resolve(projectPath, relativePath);
        if (!targetPath.startsWith(projectPath)) {
          // Clean up temp file
          if (file.path) fs.unlinkSync(file.path);
          return res.status(400).json({ code: 400, message: 'Invalid file path' });
        }
        fs.mkdirSync(path.dirname(targetPath), { recursive: true });
        // Move file from temp to target
        fs.renameSync(file.path, targetPath);
      }
    }

    const updatedProject = await prisma.project.update({
      where: { project_id: project.project_id },
      data: { path: projectPath },
    });

    res.status(201).json({ code: 201, data: updatedProject });
  } catch (error) {
    if (error instanceof Prisma.PrismaClientKnownRequestError) {
      if (error.code === 'P2025' || error.code === 'P2003') {
        return res.status(401).json({ code: 401, message: 'User not found' });
      }
    }
    console.error(error);
    res.status(500).json({ code: 500, message: 'Internal server error' });
  }
};

export const getProjects = async (req: AuthRequest, res: Response) => {
  try {
    const userId = req.user!.id;
    const projects = await prisma.project.findMany({
      where: { owner_id: userId },
      orderBy: { created_at: 'desc' },
    });
    res.json({ code: 200, data: projects });
  } catch (error) {
    res.status(500).json({ message: 'Internal server error' });
  }
};

export const getProject = async (req: AuthRequest, res: Response) => {
  try {
    const { id } = req.params;
    const userId = req.user!.id;

    const project = await prisma.project.findUnique({
      where: { project_id: id },
    });

    if (!project) {
      return res.status(404).json({ code: 404, message: 'Project not found' });
    }

    if (project.owner_id !== userId) {
      return res.status(403).json({ code: 403, message: 'Forbidden' });
    }

    res.json({ code: 200, data: project });
  } catch (error) {
    res.status(500).json({ message: 'Internal server error' });
  }
};

export const updateProject = async (req: AuthRequest, res: Response) => {
  try {
    const { id } = req.params;
    const userId = req.user!.id;
    const { name, description } = req.body;

    const project = await prisma.project.findUnique({
      where: { project_id: id },
    });

    if (!project) {
      return res.status(404).json({ code: 404, message: 'Project not found' });
    }

    if (project.owner_id !== userId) {
      return res.status(403).json({ code: 403, message: 'Forbidden' });
    }

    const updated = await prisma.project.update({
      where: { project_id: id },
      data: { name, description },
    });

    res.json({ code: 200, data: updated });
  } catch (error) {
    res.status(500).json({ message: 'Internal server error' });
  }
};

export const deleteProject = async (req: AuthRequest, res: Response) => {
  try {
    const { id } = req.params;
    const userId = req.user!.id;

    console.log(`[DELETE] Request to delete project: ${id} by user: ${userId}`);

    const project = await prisma.project.findUnique({
      where: { project_id: id },
    });

    if (!project) {
      console.log(`[DELETE] Project not found: ${id}`);
      return res.status(404).json({ code: 404, message: 'Project not found' });
    }

    if (project.owner_id !== userId) {
      console.log(`[DELETE] Forbidden access to project: ${id} by user: ${userId}`);
      return res.status(403).json({ code: 403, message: 'Forbidden' });
    }

    await prisma.project.delete({
      where: { project_id: id },
    });

    // Cleanup files
    if (project.path && fs.existsSync(project.path)) {
      fs.rmSync(project.path, { recursive: true, force: true });
    }

    console.log(`[DELETE] Project deleted successfully: ${id}`);
    res.json({ code: 200, message: 'Project deleted' });
  } catch (error) {
    console.error(`[DELETE] Error deleting project:`, error);
    res.status(500).json({ message: 'Internal server error' });
  }
};

export const getProjectStructure = async (req: AuthRequest, res: Response) => {
  try {
    const { id } = req.params;
    const { path: subPath } = req.query; // Support subPath
    const userId = req.user!.id;

    const project = await prisma.project.findUnique({
      where: { project_id: id },
    });

    if (!project) {
      return res.status(404).json({ code: 404, message: 'Project not found' });
    }

    if (project.owner_id !== userId) {
      return res.status(403).json({ code: 403, message: 'Forbidden' });
    }

    if (!project.path) {
      return res.status(400).json({ message: 'Project path not set' });
    }

    // subPath must be string or undefined
    const validSubPath = typeof subPath === 'string' ? subPath : undefined;

    const structure = await StructureService.getProjectStructure(project.path, validSubPath);
    res.json({ code: 200, data: structure });
  } catch (error) {
    console.error(error);
    res.status(500).json({ message: 'Internal server error' });
  }
};

export const getProjectFileContent = async (req: AuthRequest, res: Response) => {
  try {
    const { id } = req.params;
    const { path: filePath } = req.query;
    const userId = req.user?.id;

    if (!userId) {
      return res.status(401).json({ code: 401, message: 'Unauthorized' });
    }

    if (!filePath || typeof filePath !== 'string') {
      return res.status(400).json({ code: 400, message: 'File path is required' });
    }

    const project = await prisma.project.findUnique({
      where: { project_id: id },
    });

    if (!project) {
      return res.status(404).json({ code: 404, message: 'Project not found' });
    }

    if (project.owner_id !== userId) {
      return res.status(403).json({ code: 403, message: 'Forbidden' });
    }

    if (!project.path) {
      return res.status(400).json({ code: 400, message: 'Project path not set' });
    }

    const fullPath = path.resolve(project.path, filePath);
    if (!fullPath.startsWith(project.path)) {
      return res.status(400).json({ code: 400, message: 'Invalid file path' });
    }

    if (!fs.existsSync(fullPath)) {
      return res.status(404).json({ code: 404, message: 'File not found' });
    }

    const stat = fs.statSync(fullPath);
    if (!stat.isFile()) {
      return res.status(400).json({ code: 400, message: 'Not a file' });
    }

    const buffer = fs.readFileSync(fullPath);
    const isText = buffer.toString('utf8').indexOf('\uFFFD') === -1;
    if (!isText) {
      return res.status(415).json({ code: 415, message: '不支持预览' });
    }

    return res.json({ code: 200, data: { content: buffer.toString('utf8') } });
  } catch (error) {
    console.error(error);
    return res.status(500).json({ code: 500, message: 'Internal server error' });
  }
};
