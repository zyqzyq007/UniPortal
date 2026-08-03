import { Response } from 'express';
import prisma from '../prisma';
import { AuthRequest } from '../middleware/auth.middleware';

// Probe an OpenAI-compatible /models endpoint and classify models by capability.
// Returns { ok, models: {embedding, llm, reranker}, error? }
async function probeOpenAICompatible(baseUrl: string, apiKey: string): Promise<{
  ok: boolean;
  models: { embedding: string[]; llm: string[]; reranker: string[] };
  error?: string;
}> {
  const result = { ok: false, models: { embedding: [] as string[], llm: [] as string[], reranker: [] as string[] } };
  try {
    const url = baseUrl.replace(/\/$/, '') + '/models';
    const res = await fetch(url, {
      headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {},
      signal: AbortSignal.timeout(10000),
    });
    if (!res.ok) {
      return { ...result, error: `HTTP ${res.status}` };
    }
    const body: any = await res.json();
    const ids: string[] = (body.data || body.models || []).map((m: any) => m.id || m.name).filter(Boolean);

    // Heuristic classification by name keywords.
    // Check reranker first (e.g. "gte-rerank" would otherwise match embedding's "gte-").
    for (const id of ids) {
      const lower = id.toLowerCase();
      if (/(rerank|bge-reranker|cohere-rerank)/.test(lower)) {
        result.models.reranker.push(id);
      } else if (/(embed|bge-m3|text-embedding|e5-|gte-)/.test(lower)) {
        result.models.embedding.push(id);
      } else {
        result.models.llm.push(id);
      }
    }
    result.ok = true;
    return result;
  } catch (e: any) {
    return { ...result, error: e?.message || 'Connection failed' };
  }
}

function maskApiKey(key: string): string {
  if (!key || key.length < 8) return '***';
  return key.slice(0, 4) + '***' + key.slice(-4);
}

// List all providers for the current user
export const listProviders = async (req: AuthRequest, res: Response) => {
  try {
    const providers = await prisma.modelProvider.findMany({
      where: { owner_id: req.user!.id },
      orderBy: { created_at: 'desc' },
    });
    const data = providers.map((p) => ({
      ...p,
      api_key: maskApiKey(p.api_key),
    }));
    return res.status(200).json({ code: 200, data });
  } catch (error) {
    console.error('listProviders error:', error);
    return res.status(500).json({ code: 500, message: 'Internal server error' });
  }
};

// Create a new provider
export const createProvider = async (req: AuthRequest, res: Response) => {
  try {
    const { name, provider_type, base_url, api_key, capabilities } = req.body;
    if (!name || !provider_type || !base_url) {
      return res.status(400).json({ code: 400, message: 'name, provider_type, base_url are required' });
    }
    const provider = await prisma.modelProvider.create({
      data: {
        owner_id: req.user!.id,
        name,
        provider_type,
        base_url,
        api_key: api_key || '',
        capabilities: JSON.stringify(capabilities || []),
      },
    });
    return res.status(201).json({
      code: 201,
      data: { ...provider, api_key: maskApiKey(provider.api_key) },
    });
  } catch (error) {
    console.error('createProvider error:', error);
    return res.status(500).json({ code: 500, message: 'Internal server error' });
  }
};

// Update a provider
export const updateProvider = async (req: AuthRequest, res: Response) => {
  try {
    const { id } = req.params;
    const { name, provider_type, base_url, api_key, capabilities, is_active } = req.body;
    const existing = await prisma.modelProvider.findFirst({ where: { id, owner_id: req.user!.id } });
    if (!existing) return res.status(404).json({ code: 404, message: 'Provider not found' });

    const updated = await prisma.modelProvider.update({
      where: { id },
      data: {
        name: name ?? existing.name,
        provider_type: provider_type ?? existing.provider_type,
        base_url: base_url ?? existing.base_url,
        // Only update api_key if a non-masked value is provided
        api_key: api_key && !api_key.includes('***') ? api_key : existing.api_key,
        capabilities: capabilities ? JSON.stringify(capabilities) : existing.capabilities,
        is_active: typeof is_active === 'boolean' ? is_active : existing.is_active,
      },
    });
    return res.status(200).json({
      code: 200,
      data: { ...updated, api_key: maskApiKey(updated.api_key) },
    });
  } catch (error) {
    console.error('updateProvider error:', error);
    return res.status(500).json({ code: 500, message: 'Internal server error' });
  }
};

// Delete a provider
export const deleteProvider = async (req: AuthRequest, res: Response) => {
  try {
    const { id } = req.params;
    const existing = await prisma.modelProvider.findFirst({ where: { id, owner_id: req.user!.id } });
    if (!existing) return res.status(404).json({ code: 404, message: 'Provider not found' });

    await prisma.modelProvider.delete({ where: { id } });
    return res.status(200).json({ code: 200, message: 'Provider deleted' });
  } catch (error) {
    console.error('deleteProvider error:', error);
    return res.status(500).json({ code: 500, message: 'Internal server error' });
  }
};

// Test connection and fetch available models
export const testProvider = async (req: AuthRequest, res: Response) => {
  try {
    const { id } = req.params;
    const provider = await prisma.modelProvider.findFirst({ where: { id, owner_id: req.user!.id } });
    if (!provider) return res.status(404).json({ code: 404, message: 'Provider not found' });

    const probe = await probeOpenAICompatible(provider.base_url, provider.api_key);

    const updated = await prisma.modelProvider.update({
      where: { id },
      data: {
        last_tested_at: new Date(),
        last_test_ok: probe.ok,
        // Only update available_models on success — preserve last known good state on failure
        ...(probe.ok ? { available_models: JSON.stringify(probe.models) } : {}),
      },
    });

    return res.status(200).json({
      code: 200,
      data: {
        ok: probe.ok,
        error: probe.error,
        models: probe.models,
        provider: { ...updated, api_key: maskApiKey(updated.api_key) },
      },
    });
  } catch (error) {
    console.error('testProvider error:', error);
    return res.status(500).json({ code: 500, message: 'Internal server error' });
  }
};

// Get all available models across all active providers (for KB config dropdown)
export const listAvailableModels = async (req: AuthRequest, res: Response) => {
  try {
    const providers = await prisma.modelProvider.findMany({
      where: { owner_id: req.user!.id, is_active: true },
    });
    const merged = { embedding: [] as string[], llm: [] as string[], reranker: [] as string[] };
    for (const p of providers) {
      try {
        const models = JSON.parse(p.available_models || '{}');
        for (const cap of ['embedding', 'llm', 'reranker'] as const) {
          if (Array.isArray(models[cap])) {
            merged[cap].push(...models[cap].map((m: string) => `${p.name}/${m}`));
          }
        }
      } catch { /* skip invalid JSON */ }
    }
    return res.status(200).json({ code: 200, data: merged });
  } catch (error) {
    console.error('listAvailableModels error:', error);
    return res.status(500).json({ code: 500, message: 'Internal server error' });
  }
};
