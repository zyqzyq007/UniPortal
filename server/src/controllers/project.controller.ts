import { Request, Response } from 'express';
import path from 'path';
import fs from 'fs';
import { randomUUID } from 'crypto';
import prisma from '../prisma';
import { Prisma } from '@prisma/client';
import { AuthRequest } from '../middleware/auth.middleware';
import AdmZip from 'adm-zip';
import { createExtractorFromData } from 'node-unrar-js';

import { recoverZipFilename } from '../utils/encoding';

const STORAGE_ROOT = path.join(__dirname, '../../storage');

// Supported archive formats and their extensions
const ARCHIVE_EXTRACTORS: Record<string, string[]> = {
  zip: ['.zip'],
  rar: ['.rar'],
};

const SUPPORTED_EXTENSIONS = Object.values(ARCHIVE_EXTRACTORS).flat();

// Extract zip archive entry-by-entry with encoding recovery
function extractZip(archivePath: string, destDir: string): void {
  const zip = new AdmZip(archivePath);
  for (const entry of zip.getEntries()) {
    const correctedName = recoverZipFilename(entry.entryName);
    const targetPath = path.join(destDir, correctedName);
    if (entry.isDirectory) {
      fs.mkdirSync(targetPath, { recursive: true });
    } else {
      const dir = path.dirname(targetPath);
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(targetPath, entry.getData());
    }
  }
}

// Extract RAR archive using node-unrar-js (WASM-based, no system deps)
async function extractRar(archivePath: string, destDir: string): Promise<void> {
  const buf = fs.readFileSync(archivePath);
  const data = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer;
  const extractor = await createExtractorFromData({ data });
  const extracted = extractor.extract({});
  for (const file of extracted.files) {
    if (file.extraction && file.fileHeader) {
      const targetPath = path.join(destDir, file.fileHeader.name);
      const dir = path.dirname(targetPath);
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(targetPath, file.extraction);
    }
  }
}

// Ensure storage root exists
if (!fs.existsSync(STORAGE_ROOT)) {
  fs.mkdirSync(STORAGE_ROOT, { recursive: true });
}

// Write project_manifest.json under {storage}/{projectId}/{itemFilePath}/uniportal/
// Called after each software item upload. Writes INSIDE the item's disk directory so
// the manifest travels with the item (visible in file tree, readable by sub-tools).
// NOTE: itemFilePath is the on-disk UUID (SoftwareItem.file_path), NOT the item_id.
async function writeProjectManifest(projectId: string, itemFilePath: string) {
  const project = await prisma.testProject.findUnique({
    where: { project_id: projectId },
    include: {
      owner: { select: { username: true } },
      software_items: { select: { item_id: true, file_path: true, file_size: true, name: true, uploaded_at: true, version: true } },
    },
  });
  if (!project) return;

  const totalSize = project.software_items.reduce((s, it) => s + Number(it.file_size), 0);
  const currentItem = project.software_items.find((it) => it.file_path === itemFilePath);
  const manifest = {
    manifest_version: '1.0',
    project_id: project.project_id,
    project_name: project.name,
    description: project.description,
    owner: project.owner.username,
    created_at: project.created_at,
    last_upload_at: project.last_upload_at,
    item_count: project.item_count,
    total_size_bytes: totalSize.toString(),
    current_item: currentItem ? {
      item_id: currentItem.item_id,
      name: currentItem.name,
      version: currentItem.version,
      uploaded_at: currentItem.uploaded_at,
      size_bytes: currentItem.file_size.toString(),
    } : null,
    all_items: project.software_items.map((it) => ({
      item_id: it.item_id,
      name: it.name,
      version: it.version,
      uploaded_at: it.uploaded_at,
      size_bytes: it.file_size.toString(),
    })),
    generated_at: new Date().toISOString(),
  };

  // Write inside the item's disk directory so it's visible in the file tree
  const manifestDir = path.join(STORAGE_ROOT, projectId, itemFilePath, 'uniportal');
  fs.mkdirSync(manifestDir, { recursive: true });
  fs.writeFileSync(
    path.join(manifestDir, 'project_manifest.json'),
    JSON.stringify(manifest, null, 2),
    'utf-8'
  );
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

        const ext = path.extname(archiveFile.originalname).toLowerCase();
        if (!SUPPORTED_EXTENSIONS.includes(ext)) {
          fs.unlinkSync(archiveFile.path);
          return res.status(400).json({
            code: 400,
            message: `不支持的压缩格式 (${ext})，仅支持 ${SUPPORTED_EXTENSIONS.join(', ')} 格式`
          });
        }

        // Extract archive into UUID-named directory
        try {
            if (ext === '.zip') {
                extractZip(archiveFile.path, finalItemPath);
            } else if (ext === '.rar') {
                await extractRar(archiveFile.path, finalItemPath);
            }
            totalSize = archiveFile.size;

            // Remove temp archive
            fs.unlinkSync(archiveFile.path);
        } catch (err) {
            console.error('Archive extraction error:', err);
            if (fs.existsSync(archiveFile.path)) {
              fs.unlinkSync(archiveFile.path);
            }
            return res.status(400).json({
              code: 400,
              message: `解压失败，请确认文件为有效的 ${ext} 格式压缩包`
            });
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

        // uploadedFiles.forEach((file, index) => {
        //     const relPath = relativePaths[index] || file.originalname;
        //     const destPath = path.join(finalItemPath, relPath);
        //     const destDir = path.dirname(destPath);
        //     if (!fs.existsSync(destDir)) fs.mkdirSync(destDir, { recursive: true });
            
        //     fs.renameSync(file.path, destPath);
        //     totalSize += file.size;
        // });
        uploadedFiles.forEach((file, index) => {
            const relPath = relativePaths[index] || file.originalname;
            const destPath = path.join(finalItemPath, relPath);
            const destDir = path.dirname(destPath);
            if (!fs.existsSync(destDir)) fs.mkdirSync(destDir, { recursive: true });
            
            fs.copyFileSync(file.path, destPath);
            fs.unlinkSync(file.path);
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

    // Refresh project_manifest.json (best-effort, never block upload on it)
    // NOTE: item.file_path is the on-disk UUID directory (where extracted files live),
    // NOT item.item_id (which is the Prisma record ID — a different UUID).
    try {
        await writeProjectManifest(id, item.file_path);
    } catch (e) {
        console.warn(`writeProjectManifest failed for ${id}/${item.file_path}:`, e);
    }

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
            // res.attachment 用 content-disposition 库正确编码文件名(含中文, filename*=UTF-8)
            // 并按扩展名设置 Content-Type, 避免手动 setHeader 中文值导致 ERR_INVALID_CHAR
            res.attachment(downloadName);
            res.send(zip.toBuffer());
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

// --- 代码统计 (工程概览真实数据: 实时扫描共享卷源码计算, 不依赖子工具回传) ---

const _SOURCE_EXT = new Set(['.c', '.cc', '.cpp', '.cxx']);
const _HEADER_EXT = new Set(['.h', '.hpp', '.hxx']);
const _SKIP_DIRS = new Set(['.git', 'node_modules', '.svn', '.idea', '.vscode', '__pycache__']);
const _DOC_EXT = new Set(['.docx', '.doc', '.pdf', '.md', '.rtf', '.odt']);   // 需求/设计文档
const _DATA_EXT = new Set(['.json', '.xml', '.yaml', '.yml', '.csv']);         // 结构化数据
const _MAX_FILE_BYTES = 2 * 1024 * 1024; // 单文件 > 2MB 跳过行级解析, 避免大文件拖慢

// 近似函数计数: 非控制流的 "){" 块数 = 所有 "){" - if/for/while/switch
function _countFunctions(content: string): number {
    const noComments = content
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/\/\/[^\n]*/g, '');
    const braceBlocks = (noComments.match(/\)\s*\{/g) || []).length;
    const ctrlFlow = (noComments.match(/\b(if|for|while|switch)\s*\(/g) || []).length;
    return Math.max(0, braceBlocks - ctrlFlow);
}

// 解析 requirements.json: 兼容 [{module,requirements:[{type}]}] / {requirements:[]} / [{type}]
function _parseRequirements(jsonPath: string, stats: any) {
    try {
        const data = JSON.parse(fs.readFileSync(jsonPath, 'utf-8'));
        const addReq = (r: any) => {
            stats.requirements.items++;
            const t = r && r.type ? String(r.type) : '未分类';
            stats.requirements.types[t] = (stats.requirements.types[t] || 0) + 1;
        };
        const handleNode = (node: any) => {
            if (node && Array.isArray(node.requirements)) node.requirements.forEach(addReq);
            else if (node && (node.type || node.code || node.title)) addReq(node);
        };
        if (Array.isArray(data)) data.forEach(handleNode);
        else if (data && Array.isArray(data.requirements)) data.requirements.forEach(addReq);
    } catch {
        // JSON 解析失败跳过 (可能不是需求文件)
    }
}

function _scanDir(dir: string, stats: any) {
    let entries: fs.Dirent[];
    try {
        entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
        return;
    }
    for (const entry of entries) {
        if (entry.isDirectory() && (entry.name.startsWith('.') || _SKIP_DIRS.has(entry.name))) continue;
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) {
            _scanDir(full, stats);
            continue;
        }
        const ext = path.extname(entry.name).toLowerCase();
        const isSource = _SOURCE_EXT.has(ext);
        const isHeader = _HEADER_EXT.has(ext);
        const isDoc = _DOC_EXT.has(ext);
        const isData = _DATA_EXT.has(ext);
        if (isSource) stats.files.source++;
        else if (isHeader) stats.files.header++;
        else if (isDoc) stats.files.doc++;
        else if (isData) stats.files.data++;
        else stats.files.other++;
        stats.files.total++;
        const typeKey = ext || '(无扩展名)';
        stats.fileTypes[typeKey] = (stats.fileTypes[typeKey] || 0) + 1;
        // 需求条目文件: requirements/ 目录下的 .txt
        if (ext === '.txt' && path.basename(dir).toLowerCase() === 'requirements') {
            stats.requirements.reqFiles++;
        }
        // 需求结构化文件: 文件名含 requirement 的 .json, 留待主函数解析
        if (ext === '.json' && entry.name.toLowerCase().includes('requirement')) {
            stats._reqJsonPaths.push(full);
        }
        if (isSource || isHeader) {
            try {
                if (fs.statSync(full).size > _MAX_FILE_BYTES) continue;
                const content = fs.readFileSync(full, 'utf-8');
                let inBlock = false;
                for (const raw of content.split(/\r?\n/)) {
                    const line = raw.trim();
                    stats.lines.total++;
                    if (inBlock) {
                        stats.lines.comment++;
                        if (line.includes('*/')) inBlock = false;
                        continue;
                    }
                    if (line === '') stats.lines.blank++;
                    else if (line.startsWith('//')) stats.lines.comment++;
                    else if (line.startsWith('/*')) {
                        stats.lines.comment++;
                        if (!line.includes('*/')) inBlock = true;
                    } else stats.lines.code++;
                }
                if (isSource) stats.functions.count += _countFunctions(content);
            } catch {
                // 单文件读取失败跳过, 不影响整体统计
            }
        }
    }
}

export const getProjectCodeStats = async (req: AuthRequest, res: Response) => {
    try {
        const { id } = req.params;
        const userId = req.user!.id;
        const project = await prisma.testProject.findUnique({ where: { project_id: id } });
        if (!project) return res.status(404).json({ code: 404, message: 'Project not found' });
        if (project.owner_id !== userId) return res.status(403).json({ code: 403, message: 'Forbidden' });

        const items = await prisma.softwareItem.findMany({ where: { project_id: id } });

        const stats = {
            files: { source: 0, header: 0, doc: 0, data: 0, other: 0, total: 0 },
            lines: { total: 0, code: 0, comment: 0, blank: 0 },
            functions: { count: 0 },
            fileTypes: {} as Record<string, number>,
            requirements: { items: 0, reqFiles: 0, types: {} as Record<string, number> },
            _reqJsonPaths: [] as string[],
        };

        for (const item of items) {
            const itemRoot = path.join(STORAGE_ROOT, id, item.file_path);
            if (fs.existsSync(itemRoot)) _scanDir(itemRoot, stats);
        }
        // 扫描完后统一解析收集到的需求 JSON
        for (const jp of stats._reqJsonPaths) _parseRequirements(jp, stats);

        const commentRatio = stats.lines.total > 0
            ? Math.round((stats.lines.comment / stats.lines.total) * 1000) / 10
            : 0;
        const avgFnLines = stats.functions.count > 0
            ? Math.round((stats.lines.code / stats.functions.count) * 10) / 10
            : 0;
        const fileTypes = Object.entries(stats.fileTypes)
            .map(([name, value]) => ({ name, value }))
            .sort((a, b) => b.value - a.value);
        const reqTypes = Object.entries(stats.requirements.types)
            .map(([name, value]) => ({ name, value }))
            .sort((a, b) => b.value - a.value);

        res.json({
            code: 200,
            data: {
                files: stats.files,
                lines: stats.lines,
                commentRatio,                                    // 百分比, 如 23.5
                functions: { count: stats.functions.count, avgLines: avgFnLines },
                fileTypes,                                        // [{name:'.c', value:8}, ...]
                docs: { spec: stats.files.doc, total: stats.files.doc + stats.files.data },
                requirements: {
                    items: stats.requirements.items,       // 结构化需求条目数 (requirements.json)
                    reqFiles: stats.requirements.reqFiles, // 需求条目文件数 (requirements/*.txt)
                    types: reqTypes,                        // 需求类型分布 (功能/性能/余量...)
                },
                itemCount: items.length,
            },
        });
    } catch (error) {
        console.error(error);
        res.status(500).json({ code: 500, message: 'Internal server error' });
    }
};
