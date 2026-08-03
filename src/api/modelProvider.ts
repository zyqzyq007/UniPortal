import request from '../utils/request';

export interface ModelProvider {
  id: string;
  owner_id: string;
  name: string;
  provider_type: string;  // dashscope | openai | vllm | ollama | custom
  base_url: string;
  api_key: string;  // masked
  capabilities: string;  // JSON string
  available_models: string;  // JSON string
  last_tested_at: string | null;
  last_test_ok: boolean | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AvailableModels {
  embedding: string[];
  llm: string[];
  reranker: string[];
}

export interface TestResult {
  ok: boolean;
  error?: string;
  models: AvailableModels;
  provider: ModelProvider;
}

export interface ProviderInput {
  name: string;
  provider_type: string;
  base_url: string;
  api_key?: string;
  capabilities?: string[];
  is_active?: boolean;
}

export const listProviders = (): Promise<{ code: number; data: ModelProvider[] }> => {
  return request({ url: '/model-providers', method: 'get' });
};

export const createProvider = (data: ProviderInput): Promise<{ code: number; data: ModelProvider }> => {
  return request({ url: '/model-providers', method: 'post', data });
};

export const updateProvider = (id: string, data: Partial<ProviderInput>): Promise<{ code: number; data: ModelProvider }> => {
  return request({ url: `/model-providers/${id}`, method: 'put', data });
};

export const deleteProvider = (id: string): Promise<{ code: number; message: string }> => {
  return request({ url: `/model-providers/${id}`, method: 'delete' });
};

export const testProvider = (id: string): Promise<{ code: number; data: TestResult }> => {
  return request({ url: `/model-providers/${id}/test`, method: 'post' });
};

export const listAvailableModels = (): Promise<{ code: number; data: AvailableModels }> => {
  return request({ url: '/model-providers/available-models', method: 'get' });
};
