import { reactive, readonly } from 'vue'
import { getProject } from '../api/projects'
import type { Project } from '../api/projects'

interface ProjectState {
  currentProject: Project | null
  loading: boolean
}

const state = reactive<ProjectState>({
  currentProject: null,
  loading: false
})

export const useProjectState = () => {
  const fetchProjectInfo = async (id: string) => {
    // If already loaded same project, skip
    if (state.currentProject?.project_id === id) return

    try {
      state.loading = true
      state.currentProject = null // Reset first
      const res: any = await getProject(id)
      state.currentProject = res.data
    } catch (error) {
      console.error('Failed to fetch project info', error)
      state.currentProject = null
    } finally {
      state.loading = false
    }
  }

  const clearProject = () => {
    state.currentProject = null
  }

  return {
    state: readonly(state),
    fetchProjectInfo,
    clearProject
  }
}
