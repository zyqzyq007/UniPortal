import request from '../utils/request';

export interface ProjectModelConfig {
  embedding_model: string | null;
  reranker_model: string | null;
}

export interface ApplyStep {
  step: string;
  status: string;
  detail?: string;
}

export interface ApplyResult {
  steps: ApplyStep[];
  reindexed: number;
  failed: number;
  total: number;
}

export const getModelConfig = (projectId: string): Promise<{ code: number; data: ProjectModelConfig }> => {
  return request({ url: `/projects/${projectId}/model-config`, method: 'get' });
};

export const saveModelConfig = (
  projectId: string,
  data: ProjectModelConfig
): Promise<{ code: number; data: ProjectModelConfig }> => {
  return request({ url: `/projects/${projectId}/model-config`, method: 'put', data });
};

export const applyModelConfig = (projectId: string): Promise<{ code: number; data: ApplyResult }> => {
  return request({ url: `/projects/${projectId}/model-config/apply`, method: 'post' });
};
