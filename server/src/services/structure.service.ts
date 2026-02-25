import fs from 'fs';
import path from 'path';
import ignore from 'ignore';

interface TreeNode {
  name: string;
  type: 'dir' | 'file';
  children?: TreeNode[];
  size?: number;
}

export class StructureService {
  private static cache = new Map<string, { data: TreeNode; timestamp: number }>();
  private static CACHE_TTL = 1000 * 60 * 5; // 5 minutes

  static async getProjectStructure(projectPath: string, subPath?: string): Promise<TreeNode> {
    const targetDir = subPath ? path.join(projectPath, subPath) : projectPath;
    
    // Safety check: prevent path traversal
    if (!targetDir.startsWith(projectPath)) {
      throw new Error('Invalid path');
    }

    if (!fs.existsSync(targetDir)) {
      throw new Error('Path not found');
    }

    const ig = ignore();
    const gitignorePath = path.join(projectPath, '.gitignore');
    if (fs.existsSync(gitignorePath)) {
      const gitignoreContent = fs.readFileSync(gitignorePath, 'utf-8');
      ig.add(gitignoreContent);
    }
    ig.add('.git');

    // If subPath provided, we are fetching children for that specific node
    // But to maintain consistency, we should return a root-like node or list of children
    // Let's return a virtual directory node containing the children
    
    const rootName = subPath ? path.basename(subPath) : 'root';
    const rootNode: TreeNode = {
      name: rootName,
      type: 'dir',
      children: [],
    };

    await this.scanDirectory(projectPath, targetDir, rootNode, ig, false); // false = not recursive

    return rootNode;
  }

  private static async scanDirectory(
    rootDir: string,
    currentDir: string,
    parentNode: TreeNode,
    ig: any,
    recursive: boolean
  ) {
    const files = await fs.promises.readdir(currentDir, { withFileTypes: true });

    for (const file of files) {
      const fullPath = path.join(currentDir, file.name);
      const relativePath = path.relative(rootDir, fullPath);

      if (ig.ignores(relativePath)) {
        continue;
      }

      const node: TreeNode = {
        name: file.name,
        type: file.isDirectory() ? 'dir' : 'file',
      };

      if (file.isDirectory()) {
        node.children = []; // Always initialize children array for dirs
        // If recursive, dive deeper
        if (recursive) {
          await this.scanDirectory(rootDir, fullPath, node, ig, true);
        } else {
          // If not recursive, we just mark it as directory. 
          // Frontend will see empty children and know to lazy load if needed?
          // Or we should maybe check if it has children?
          // For lazy loading, returning empty children [] is fine, 
          // but we might want a flag 'hasChildren' if possible, but reading next level is expensive.
          // Let's stick to: if it's a directory, it has children=[] (empty but present).
          // Frontend logic: if children is empty array, it might be empty dir OR not loaded.
          // We can add a custom flag later if needed, but for now let's assume 'loaded' state on frontend.
        }
        
        if (parentNode.children) {
          parentNode.children.push(node);
        }
      } else {
        const stats = await fs.promises.stat(fullPath);
        node.size = stats.size;
        if (parentNode.children) {
          parentNode.children.push(node);
        }
      }
    }
    
    // Sort: directories first, then files
    if (parentNode.children) {
      parentNode.children.sort((a, b) => {
        if (a.type === b.type) return a.name.localeCompare(b.name);
        return a.type === 'dir' ? -1 : 1;
      });
    }
  }
}
