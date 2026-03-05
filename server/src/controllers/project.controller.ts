import { Request, Response } from 'express';
import path from 'path';
import fs from 'fs';
import { randomUUID } from 'crypto';
import prisma from '../prisma';
import { Prisma } from '@prisma/client';
import { AuthRequest } from '../middleware/auth.middleware';
import AdmZip from 'adm-zip';

const STORAGE_ROOT = path.join(__dirname, '../../storage');

// Ensure storage root exists
if (!fs.existsSync(STORAGE_ROOT)) {
  fs.mkdirSync(STORAGE_ROOT, { recursive: true });
}

// --- Test Project Controllers ---

export const createProject = async (req: AuthRequest, res: Response) => {
  try {
    const { name, description } = req.body;
    if (!req.user) {
      return res.status(401).json({ code: 401, message: 'Unauthorized' });
    }
    const userId = req.user.id;

    if (!name) {
      return res.status(400).json({ code: 400, message: 'Project name is required' });
    }

    // Check naming convention (Chinese, letters, numbers, underscore)
    const nameRegex = /^[\u4e00-\u9fa5a-zA-Z0-9_]+$/;
    if (!nameRegex.test(name)) {
      return res.status(400).json({ code: 400, message: 'Project name contains invalid characters' });
    }
    if (name.length > 64) {
      return res.status(400).json({ code: 400, message: 'Project name too long (max 64 chars)' });
    }
    if (description && description.length > 500) {
      return res.status(400).json({ code: 400, message: 'Description too long (max 500 chars)' });
    }

    const project = await prisma.testProject.create({
      data: {
        name,
        description,
        owner: {
          connect: { id: userId },
        },
      },
    });

    // Create project directory
    const projectPath = path.join(STORAGE_ROOT, project.project_id);
    if (!fs.existsSync(projectPath)) {
      fs.mkdirSync(projectPath, { recursive: true });
    }

    // Update project with path (optional, as we organize by folder structure)
    await prisma.testProject.update({
      where: { project_id: project.project_id },
      data: { path: projectPath },
    });

    res.status(201).json({ code: 201, data: project });
  } catch (error) {
    console.error(error);
    res.status(500).json({ code: 500, message: 'Internal server error' });
  }
};

export const getProjects = async (req: AuthRequest, res: Response) => {
  try {
    const userId = req.user!.id;
    const { search, sort, order, page, limit } = req.query;

    const pageNum = parseInt(page as string) || 1;
    const limitNum = parseInt(limit as string) || 10;
    const skip = (pageNum - 1) * limitNum;

    const whereClause: Prisma.TestProjectWhereInput = {
      owner_id: userId,
      ...(search ? { name: { contains: search as string } } : {}),
    };

    const orderByClause: Prisma.TestProjectOrderByWithRelationInput = {};
    if (sort === 'name') {
      orderByClause.name = (order === 'asc' ? 'asc' : 'desc');
    } else {
      orderByClause.created_at = (order === 'asc' ? 'asc' : 'desc'); // Default sort
    }

    const [total, projects] = await prisma.$transaction([
      prisma.testProject.count({ where: whereClause }),
      prisma.testProject.findMany({
        where: whereClause,
        orderBy: orderByClause,
        skip,
        take: limitNum,
      }),
    ]);

    res.json({
      code: 200,
      data: {
        items: projects,
        total,
        page: pageNum,
        limit: limitNum,
        totalPages: Math.ceil(total / limitNum),
      },
    });
  } catch (error) {
    console.error(error);
    res.status(500).json({ message: 'Internal server error' });
  }
};

export const getProject = async (req: AuthRequest, res: Response) => {
  try {
    const { id } = req.params;
    const userId = req.user!.id;

    const project = await prisma.testProject.findUnique({
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

    const project = await prisma.testProject.findUnique({
      where: { project_id: id },
    });

    if (!project) {
      return res.status(404).json({ code: 404, message: 'Project not found' });
    }

    if (project.owner_id !== userId) {
      return res.status(403).json({ code: 403, message: 'Forbidden' });
    }

    const updated = await prisma.testProject.update({
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

    const project = await prisma.testProject.findUnique({
      where: { project_id: id },
    });

    if (!project) {
      return res.status(404).json({ code: 404, message: 'Project not found' });
    }

    if (project.owner_id !== userId) {
      return res.status(403).json({ code: 403, message: 'Forbidden' });
    }

    // Delete project from DB (Cascade delete should handle software items if configured, but let's be safe)
    // Note: Our schema has onDelete: Cascade for SoftwareItem -> TestProject, so items will be deleted.
    await prisma.testProject.delete({
      where: { project_id: id },
    });

    // Cleanup files
    const projectPath = path.join(STORAGE_ROOT, id);
    if (fs.existsSync(projectPath)) {
      fs.rmSync(projectPath, { recursive: true, force: true });
    }

    res.json({ code: 200, message: 'Project deleted' });
  } catch (error) {
    console.error(error);
    res.status(500).json({ message: 'Internal server error' });
  }
};

// --- Software Item Controllers ---

export const uploadSoftwareItem = async (req: AuthRequest, res: Response) => {
  try {
    const { id } = req.params;
    const userId = req.user!.id;
    const { name, version, description } = req.body;
    
    const files = req.files as Record<string, Express.Multer.File[]> | undefined;
    
    // Check if project exists
    const project = await prisma.testProject.findUnique({
        where: { project_id: id }
    });
    
    if (!project) return res.status(404).json({ code: 404, message: 'Project not found' });
    if (project.owner_id !== userId) return res.status(403).json({ code: 403, message: 'Forbidden' });

    let itemName = name;
    let totalSize = 0;
    if (description && String(description).length > 500) {
      return res.status(400).json({ code: 400, message: 'Description too long (max 500 chars)' });
    }
    const projectPath = path.join(STORAGE_ROOT, id);
    if (!fs.existsSync(projectPath)) {
        fs.mkdirSync(projectPath, { recursive: true });
    }

    // Generate a UUID as the disk directory name to avoid using user-supplied names in filesystem paths.
    // The user-visible name is stored in the DB (name field); file_path stores only this UUID.
    const itemId = randomUUID();
    const finalItemPath = path.join(projectPath, itemId);

    // Determine Upload Mode
    if (files?.archive && files.archive.length > 0) {
        // --- Archive Mode ---
        const archiveFile = files.archive[0];
        if (!itemName) itemName = path.parse(archiveFile.originalname).name;

        // Unzip into UUID-named directory
        try {
            const zip = new AdmZip(archiveFile.path);
            zip.extractAllTo(finalItemPath, true);
            totalSize = archiveFile.size;

            // Remove temp archive
            fs.unlinkSync(archiveFile.path);
        } catch (err) {
            console.error('Unzip error:', err);
            return res.status(400).json({ code: 400, message: 'Failed to decompress archive. Please ensure it is a valid zip file.' });
        }
        
    } else if (files?.files && files.files.length > 0) {
        // --- Folder Mode ---
        const uploadedFiles = files.files;
        let relativePaths: string[] = [];
        if (req.body.paths) {
            if (Array.isArray(req.body.paths)) relativePaths = req.body.paths;
            else relativePaths = [req.body.paths];
        }
        
        if (!itemName) itemName = 'Uploaded_Folder_' + Date.now();
        if (!fs.existsSync(finalItemPath)) fs.mkdirSync(finalItemPath, { recursive: true });

        uploadedFiles.forEach((file, index) => {
            const relPath = relativePaths[index] || file.originalname;
            const destPath = path.join(finalItemPath, relPath);
            const destDir = path.dirname(destPath);
            if (!fs.existsSync(destDir)) fs.mkdirSync(destDir, { recursive: true });
            
            fs.renameSync(file.path, destPath);
            totalSize += file.size;
        });

    } else {
         return res.status(400).json({ code: 400, message: 'No file uploaded' });
    }

    // Create SoftwareItem record.
    // file_path stores the UUID directory name (NOT the user-visible name),
    // so filesystem paths are always safe and unambiguous.
    const item = await prisma.softwareItem.create({
        data: {
            name: itemName,           // user-visible display name
            description: description || null,
            version: version || '1.0.0',
            file_path: itemId,        // UUID — the actual disk directory name
            file_size: BigInt(totalSize),
            project: { connect: { project_id: id } },
            created_by_user: { connect: { id: userId } }
        }
    });

    // Update Project stats
    await prisma.testProject.update({
        where: { project_id: id },
        data: {
            item_count: { increment: 1 },
            last_upload_at: new Date(),
            updated_at: new Date()
        }
    });

    const itemData = {
        ...item,
        file_size: item.file_size.toString()
    };

    res.status(201).json({ code: 201, data: itemData });

  } catch (error) {
    console.error(error);
    res.status(500).json({ message: 'Internal server error' });
  }
};

export const getSoftwareItems = async (req: AuthRequest, res: Response) => {
    try {
        const { id } = req.params;
        const userId = req.user!.id;
        const { search, page, limit } = req.query;
        
        const project = await prisma.testProject.findUnique({ where: { project_id: id } });
        if (!project) return res.status(404).json({ code: 404, message: 'Project not found' });
        if (project.owner_id !== userId) return res.status(403).json({ code: 403, message: 'Forbidden' });

        const pageNum = parseInt(page as string) || 1;
        const limitNum = parseInt(limit as string) || 10;
        const skip = (pageNum - 1) * limitNum;

        const whereClause: Prisma.SoftwareItemWhereInput = {
            project_id: id,
            ...(search ? { name: { contains: search as string } } : {})
        };

        const [total, items] = await prisma.$transaction([
            prisma.softwareItem.count({ where: whereClause }),
            prisma.softwareItem.findMany({
                where: whereClause,
                orderBy: { uploaded_at: 'desc' },
                skip,
                take: limitNum
            })
        ]);
        
        const serializedItems = items.map(item => ({
            ...item,
            file_size: item.file_size.toString()
        }));

        res.json({
            code: 200,
            data: {
                items: serializedItems,
                total,
                page: pageNum,
                limit: limitNum,
                totalPages: Math.ceil(total / limitNum)
            }
        });

    } catch (error) {
        console.error(error);
        res.status(500).json({ message: 'Internal server error' });
    }
};

export const deleteSoftwareItem = async (req: AuthRequest, res: Response) => {
    try {
        const { id, itemId } = req.params;
        const userId = req.user!.id;

        const project = await prisma.testProject.findUnique({ where: { project_id: id } });
        if (!project) return res.status(404).json({ code: 404, message: 'Project not found' });
        if (project.owner_id !== userId) return res.status(403).json({ code: 403, message: 'Forbidden' });
        
        const item = await prisma.softwareItem.findUnique({ where: { item_id: itemId } });
        if (!item) return res.status(404).json({ code: 404, message: 'Item not found' });
        if (item.project_id !== id) return res.status(400).json({ code: 400, message: 'Item does not belong to this project' });

        // Delete from DB
        await prisma.softwareItem.delete({ where: { item_id: itemId } });
        
        // Delete file
        const filePath = path.join(STORAGE_ROOT, id, item.file_path);
        if (fs.existsSync(filePath)) {
            fs.rmSync(filePath, { recursive: true, force: true });
        }

        // Update Project stats
        await prisma.testProject.update({
            where: { project_id: id },
            data: {
                item_count: { decrement: 1 },
                updated_at: new Date()
            }
        });

        res.json({ code: 200, message: 'Item deleted' });

    } catch (error) {
        console.error(error);
        res.status(500).json({ message: 'Internal server error' });
    }
};

export const downloadSoftwareItem = async (req: AuthRequest, res: Response) => {
    try {
        const { id, itemId } = req.params;
        const userId = req.user!.id;

        const project = await prisma.testProject.findUnique({ where: { project_id: id } });
        if (!project) return res.status(404).json({ code: 404, message: 'Project not found' });
        if (project.owner_id !== userId) return res.status(403).json({ code: 403, message: 'Forbidden' });
        
        const item = await prisma.softwareItem.findUnique({ where: { item_id: itemId } });
        if (!item) return res.status(404).json({ code: 404, message: 'Item not found' });

        const filePath = path.join(STORAGE_ROOT, id, item.file_path);
        if (!fs.existsSync(filePath)) {
            return res.status(404).json({ code: 404, message: 'File not found on disk' });
        }

        // Check if it is a directory
        const stats = fs.statSync(filePath);
        if (stats.isDirectory()) {
            // Zip it on the fly or deny?
            // Requirement says "Download". Usually we zip directories.
            // Let's use adm-zip to zip it to stream.
            const zip = new AdmZip();
            zip.addLocalFolder(filePath);
            const downloadName = `${item.name}.zip`;
            res.setHeader('Content-Type', 'application/zip');
            res.setHeader('Content-Disposition', `attachment; filename=${downloadName}`);
            const buffer = zip.toBuffer();
            res.send(buffer);
        } else {
            res.download(filePath, item.name);
        }

    } catch (error) {
        console.error(error);
        res.status(500).json({ message: 'Internal server error' });
    }
};

const resolveSafePath = (basePath: string, targetPath: string) => {
    const resolved = path.resolve(basePath, targetPath);
    if (!resolved.startsWith(path.resolve(basePath))) {
        throw new Error('Invalid path');
    }
    return resolved;
};

const ensureProjectItem = async (projectId: string, itemId: string, userId: string) => {
    const project = await prisma.testProject.findUnique({ where: { project_id: projectId } });
    if (!project) {
        return { error: { code: 404, message: 'Project not found' } };
    }
    if (project.owner_id !== userId) {
        return { error: { code: 403, message: 'Forbidden' } };
    }
    const item = await prisma.softwareItem.findUnique({ where: { item_id: itemId } });
    if (!item || item.project_id !== projectId) {
        return { error: { code: 404, message: 'Item not found' } };
    }
    return { item };
};

const hasError = (
    result: Awaited<ReturnType<typeof ensureProjectItem>>
): result is { error: { code: number; message: string } } => {
    return 'error' in result;
};

const detectMimeAndLanguage = (filePath: string) => {
    const ext = path.extname(filePath).toLowerCase();
    const map: Record<string, { mime: string; language: string; binary: boolean }> = {
        '.js': { mime: 'text/javascript', language: 'javascript', binary: false },
        '.jsx': { mime: 'text/javascript', language: 'javascript', binary: false },
        '.ts': { mime: 'text/typescript', language: 'typescript', binary: false },
        '.tsx': { mime: 'text/typescript', language: 'typescript', binary: false },
        '.json': { mime: 'application/json', language: 'json', binary: false },
        '.md': { mime: 'text/markdown', language: 'markdown', binary: false },
        '.vue': { mime: 'text/plain', language: 'html', binary: false },
        '.html': { mime: 'text/html', language: 'html', binary: false },
        '.htm': { mime: 'text/html', language: 'html', binary: false },
        '.css': { mime: 'text/css', language: 'css', binary: false },
        '.scss': { mime: 'text/x-scss', language: 'scss', binary: false },
        '.less': { mime: 'text/x-less', language: 'less', binary: false },
        '.py': { mime: 'text/x-python', language: 'python', binary: false },
        '.java': { mime: 'text/x-java-source', language: 'java', binary: false },
        '.c': { mime: 'text/x-c', language: 'c', binary: false },
        '.cpp': { mime: 'text/x-c', language: 'cpp', binary: false },
        '.h': { mime: 'text/x-c', language: 'cpp', binary: false },
        '.cs': { mime: 'text/plain', language: 'csharp', binary: false },
        '.go': { mime: 'text/plain', language: 'go', binary: false },
        '.rs': { mime: 'text/plain', language: 'rust', binary: false },
        '.php': { mime: 'text/x-php', language: 'php', binary: false },
        '.rb': { mime: 'text/x-ruby', language: 'ruby', binary: false },
        '.sh': { mime: 'text/x-sh', language: 'shell', binary: false },
        '.bat': { mime: 'text/plain', language: 'bat', binary: false },
        '.xml': { mime: 'text/xml', language: 'xml', binary: false },
        '.yml': { mime: 'text/yaml', language: 'yaml', binary: false },
        '.yaml': { mime: 'text/yaml', language: 'yaml', binary: false },
        '.sql': { mime: 'text/plain', language: 'sql', binary: false },
        '.ini': { mime: 'text/plain', language: 'ini', binary: false },
        '.conf': { mime: 'text/plain', language: 'plaintext', binary: false },
        '.txt': { mime: 'text/plain', language: 'plaintext', binary: false },
        '.log': { mime: 'text/plain', language: 'plaintext', binary: false },
        '.gitignore': { mime: 'text/plain', language: 'plaintext', binary: false },
        '.env': { mime: 'text/plain', language: 'plaintext', binary: false },
        '.png': { mime: 'image/png', language: 'plaintext', binary: true },
        '.jpg': { mime: 'image/jpeg', language: 'plaintext', binary: true },
        '.jpeg': { mime: 'image/jpeg', language: 'plaintext', binary: true },
        '.gif': { mime: 'image/gif', language: 'plaintext', binary: true },
        '.webp': { mime: 'image/webp', language: 'plaintext', binary: true },
        '.pdf': { mime: 'application/pdf', language: 'plaintext', binary: true },
        '.zip': { mime: 'application/zip', language: 'plaintext', binary: true },
        '.rar': { mime: 'application/x-rar-compressed', language: 'plaintext', binary: true },
        '.7z': { mime: 'application/x-7z-compressed', language: 'plaintext', binary: true },
        '.tar': { mime: 'application/x-tar', language: 'plaintext', binary: true },
        '.gz': { mime: 'application/gzip', language: 'plaintext', binary: true }
    };
    return map[ext] || { mime: 'application/octet-stream', language: 'plaintext', binary: true };
};

export const getSoftwareItemStructure = async (req: AuthRequest, res: Response) => {
    try {
        const { id, itemId } = req.params;
        const userId = req.user!.id;
        const nodePath = (req.query.path as string) || '';
        const result = await ensureProjectItem(id, itemId, userId);
        if (hasError(result)) {
            return res.status(result.error.code).json(result.error);
        }

        const itemRoot = path.join(STORAGE_ROOT, id, result.item.file_path);
        const targetDir = resolveSafePath(itemRoot, nodePath || '.');
        if (!fs.existsSync(targetDir)) {
            return res.status(404).json({ code: 404, message: 'Path not found' });
        }
        const stat = fs.statSync(targetDir);
        if (!stat.isDirectory()) {
            return res.status(400).json({ code: 400, message: 'Path is not a directory' });
        }

        const entries = fs.readdirSync(targetDir, { withFileTypes: true }).map((entry) => {
            const fullPath = path.join(targetDir, entry.name);
            const entryStat = fs.statSync(fullPath);
            const relativePath = path.relative(itemRoot, fullPath).split(path.sep).join('/');
            return {
                name: entry.name,
                type: entry.isDirectory() ? 'dir' : 'file',
                path: relativePath,
                size: entry.isFile() ? entryStat.size : undefined,
                updated_at: entryStat.mtime.toISOString(),
                children: entry.isDirectory() ? [] : undefined
            };
        });

        entries.sort((a, b) => {
            if (a.type === b.type) return a.name.localeCompare(b.name);
            return a.type === 'dir' ? -1 : 1;
        });

        return res.json({
            code: 200,
            data: {
                name: nodePath ? path.basename(nodePath) : result.item.name,
                path: nodePath,
                type: 'dir',
                children: entries
            }
        });
    } catch (error) {
        console.error(error);
        return res.status(500).json({ code: 500, message: 'Internal server error' });
    }
};

export const getSoftwareItemFileContent = async (req: AuthRequest, res: Response) => {
    try {
        const { id, itemId } = req.params;
        const userId = req.user!.id;
        const filePath = (req.query.path as string) || '';
        const allowLarge = req.query.allowLarge === 'true';
        const offset = Number(req.query.offset || 0);
        const limit = Number(req.query.limit || 262144);
        const result = await ensureProjectItem(id, itemId, userId);
        if (hasError(result)) {
            return res.status(result.error.code).json(result.error);
        }
        if (!filePath) {
            return res.status(400).json({ code: 400, message: 'Path is required' });
        }

        const itemRoot = path.join(STORAGE_ROOT, id, result.item.file_path);
        const fullPath = resolveSafePath(itemRoot, filePath);
        if (!fs.existsSync(fullPath)) {
            return res.status(404).json({ code: 404, message: 'File not found' });
        }
        const stat = fs.statSync(fullPath);
        if (!stat.isFile()) {
            return res.status(400).json({ code: 400, message: 'Path is not a file' });
        }

        const meta = detectMimeAndLanguage(fullPath);
        if (!meta.binary && stat.size > 1024 * 1024 && !allowLarge) {
            return res.status(413).json({ code: 413, message: 'File too large, confirm before loading', data: { size: stat.size } });
        }

        if (meta.binary) {
            const buf = fs.readFileSync(fullPath);
            return res.json({
                code: 200,
                data: {
                    kind: 'binary',
                    path: filePath,
                    size: stat.size,
                    updated_at: stat.mtime.toISOString(),
                    language: meta.language,
                    mime_type: meta.mime,
                    content_base64: buf.toString('base64')
                }
            });
        }

        if (allowLarge && stat.size > 1024 * 1024) {
            const fd = fs.openSync(fullPath, 'r');
            const chunkSize = Math.max(Math.min(limit, stat.size - offset), 0);
            const buffer = Buffer.alloc(chunkSize);
            fs.readSync(fd, buffer, 0, chunkSize, offset);
            fs.closeSync(fd);
            return res.json({
                code: 200,
                data: {
                    kind: 'text',
                    path: filePath,
                    size: stat.size,
                    updated_at: stat.mtime.toISOString(),
                    language: meta.language,
                    mime_type: meta.mime,
                    content: buffer.toString('utf-8'),
                    offset,
                    limit: chunkSize,
                    eof: offset + chunkSize >= stat.size
                }
            });
        }

        const content = fs.readFileSync(fullPath, 'utf-8');
        return res.json({
            code: 200,
            data: {
                kind: 'text',
                path: filePath,
                size: stat.size,
                updated_at: stat.mtime.toISOString(),
                language: meta.language,
                mime_type: meta.mime,
                content
            }
        });
    } catch (error) {
        console.error(error);
        return res.status(500).json({ code: 500, message: 'Internal server error' });
    }
};

export const operateSoftwareItemNode = async (req: AuthRequest, res: Response) => {
    try {
        const { id, itemId } = req.params;
        const userId = req.user!.id;
        const { action, path: nodePath, newName } = req.body as {
            action: 'new_file' | 'new_folder' | 'rename' | 'delete';
            path: string;
            newName?: string;
        };
        const result = await ensureProjectItem(id, itemId, userId);
        if (hasError(result)) {
            return res.status(result.error.code).json(result.error);
        }
        if (!action || !nodePath) {
            return res.status(400).json({ code: 400, message: 'action and path are required' });
        }

        const itemRoot = path.join(STORAGE_ROOT, id, result.item.file_path);
        const fullPath = resolveSafePath(itemRoot, nodePath);

        if (action === 'new_file') {
            const dir = path.dirname(fullPath);
            fs.mkdirSync(dir, { recursive: true });
            if (!fs.existsSync(fullPath)) {
                fs.writeFileSync(fullPath, '');
            }
        } else if (action === 'new_folder') {
            fs.mkdirSync(fullPath, { recursive: true });
        } else if (action === 'rename') {
            if (!newName) {
                return res.status(400).json({ code: 400, message: 'newName is required for rename' });
            }
            const target = resolveSafePath(path.dirname(fullPath), newName);
            fs.renameSync(fullPath, target);
        } else if (action === 'delete') {
            if (fs.existsSync(fullPath)) {
                fs.rmSync(fullPath, { recursive: true, force: true });
            }
        }

        return res.json({ code: 200, message: 'ok' });
    } catch (error) {
        console.error(error);
        return res.status(500).json({ code: 500, message: 'Internal server error' });
    }
};
