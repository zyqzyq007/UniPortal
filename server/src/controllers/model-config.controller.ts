import { Response } from 'express';
import { writeFileSync, mkdirSync } from 'fs';
import path from 'path';
import Docker from 'dockerode';
import prisma from '../prisma';
import { AuthRequest } from '../middleware/auth.middleware';

const RAG_DATA_PATH = process.env.RAG_DATA_PATH || '/app/rag-data';
const RAG_CONTAINER_NAME = process.env.RAG_CONTAINER_NAME || 'uni-rag';
const RAG_SERVICE_URL = process.env.RAG_SERVICE_URL || 'http://rag:8000';

const docker = new Docker({ socketPath: '/var/run/docker.sock' });

// Save model selection to project
export const saveModelConfig = async (req: AuthRequest, res: Response) => {
  try {
    const { id } = req.params;
    const { embeddingModel, rerankerModel } = req.body;

    const project = await prisma.testProject.findFirst({
      where: { project_id: id, owner_id: req.user!.id },
    });
    if (!project) {
      return res.status(404).json({ code: 404, message: 'Project not found' });
    }

    const updated = await prisma.testProject.update({
      where: { project_id: id },
      data: {
        embedding_model: embeddingModel || null,
        reranker_model: rerankerModel || null,
      },
    });

    return res.status(200).json({
      code: 200,
      data: {
        embedding_model: updated.embedding_model,
        reranker_model: updated.reranker_model,
      },
    });
  } catch (error) {
    console.error('saveModelConfig error:', error);
    return res.status(500).json({ code: 500, message: 'Internal server error' });
  }
};

// Get model config for a project
export const getModelConfig = async (req: AuthRequest, res: Response) => {
  try {
    const { id } = req.params;
    const project = await prisma.testProject.findFirst({
      where: { project_id: id, owner_id: req.user!.id },
      select: { embedding_model: true, reranker_model: true },
    });
    if (!project) {
      return res.status(404).json({ code: 404, message: 'Project not found' });
    }
    return res.status(200).json({ code: 200, data: project });
  } catch (error) {
    console.error('getModelConfig error:', error);
    return res.status(500).json({ code: 500, message: 'Internal server error' });
  }
};

// Look up provider config for a "ProviderName/model_id" string
async function resolveProvider(modelSpec: string | null) {
  if (!modelSpec) return null;
  const slashIdx = modelSpec.indexOf('/');
  if (slashIdx < 0) return null;
  const providerName = modelSpec.slice(0, slashIdx);
  const modelId = modelSpec.slice(slashIdx + 1);

  const provider = await prisma.modelProvider.findFirst({
    where: { name: providerName },
  });
  if (!provider) return null;
  return { provider, modelId };
}

// Apply model config: write env file → restart RAG → trigger reindex
export const applyModelConfig = async (req: AuthRequest, res: Response) => {
  try {
    const { id } = req.params;
    const project = await prisma.testProject.findFirst({
      where: { project_id: id, owner_id: req.user!.id },
    });
    if (!project) {
      return res.status(404).json({ code: 404, message: 'Project not found' });
    }

    const steps: Array<{ step: string; status: string; detail?: string }> = [];

    // 1. Resolve provider configs
    const embProvider = await resolveProvider(project.embedding_model);
    const rerankProvider = await resolveProvider(project.reranker_model);

    if (project.embedding_model && !embProvider) {
      steps.push({ step: 'resolve_embedding', status: 'failed', detail: 'Provider not found' });
      return res.status(400).json({ code: 400, message: 'Embedding provider not found', steps });
    }

    // 2. Generate env override file
    const envLines: string[] = [];
    if (embProvider) {
      envLines.push(`EMBEDDING_PROVIDER=api`);
      envLines.push(`EMBEDDING_MODEL=${embProvider.modelId}`);
      envLines.push(`OPENAI_BASE_URL=${embProvider.provider.base_url}`);
      envLines.push(`OPENAI_API_KEY=${embProvider.provider.api_key}`);
    }
    if (rerankProvider) {
      envLines.push(`RERANKER_ENABLED=true`);
      envLines.push(`RERANKER_MODEL=${rerankProvider.modelId}`);
    }

    const envContent = envLines.join('\n') + '\n';
    steps.push({ step: 'generate_env', status: 'done', detail: `${envLines.length} vars` });

    // 3. Write override file to shared volume
    try {
      mkdirSync(RAG_DATA_PATH, { recursive: true });
      writeFileSync(path.join(RAG_DATA_PATH, 'rag_override.env'), envContent, 'utf-8');
      steps.push({ step: 'write_env', status: 'done' });
    } catch (e: any) {
      steps.push({ step: 'write_env', status: 'failed', detail: e?.message });
      return res.status(500).json({ code: 500, message: 'Failed to write env file', steps });
    }

    // 4. Restart RAG container
    try {
      const container = docker.getContainer(RAG_CONTAINER_NAME);
      const info = await container.inspect();
      if (!info.State.Running) {
        steps.push({ step: 'restart_rag', status: 'skipped', detail: 'Container not running' });
      } else {
        await container.restart();
        // Wait for RAG to be healthy (poll up to 60s)
        let healthy = false;
        for (let i = 0; i < 30; i++) {
          await new Promise((r) => setTimeout(r, 2000));
          try {
            const r = await fetch(`${RAG_SERVICE_URL}/api/admin/health`);
            if (r.ok) {
              const body: any = await r.json();
              if (body.status === 'healthy') { healthy = true; break; }
            }
          } catch { /* retry */ }
        }
        steps.push({
          step: 'restart_rag',
          status: healthy ? 'done' : 'timeout',
          detail: healthy ? 'Healthy' : 'Did not become healthy in 60s',
        });
        if (!healthy) {
          return res.status(200).json({ code: 200, data: { steps, reindexed: false } });
        }
      }
    } catch (e: any) {
      steps.push({ step: 'restart_rag', status: 'failed', detail: e?.message });
      return res.status(500).json({ code: 500, message: 'Failed to restart RAG', steps });
    }

    // 5. Trigger reindex for all knowledge documents in this project
    const docs = await prisma.knowledgeDocument.findMany({
      where: { project_id: id },
      select: { rag_document_id: true, filename: true },
    });

    let reindexed = 0;
    let failed = 0;
    for (const doc of docs) {
      try {
        const r = await fetch(`${RAG_SERVICE_URL}/api/documents/${doc.rag_document_id}/reindex`, {
          method: 'POST',
        });
        if (r.ok) reindexed++;
        else failed++;
      } catch {
        failed++;
      }
    }
    steps.push({ step: 'reindex', status: 'done', detail: `${reindexed}/${docs.length} succeeded` });

    return res.status(200).json({
      code: 200,
      data: {
        steps,
        reindexed,
        failed,
        total: docs.length,
      },
    });
  } catch (error) {
    console.error('applyModelConfig error:', error);
    return res.status(500).json({ code: 500, message: 'Internal server error' });
  }
};
