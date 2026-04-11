import { defineStore } from 'pinia'

export const useAppStore = defineStore('app', {
  state: () => ({
    projectId: localStorage.getItem('projectId') || null,
    projectName: localStorage.getItem('projectName') || null,
    functionId: localStorage.getItem('functionId') || null,
    functionName: localStorage.getItem('functionName') || null,
    taskId: localStorage.getItem('taskId') || null,
    failureContext: null,
    failedTaskId: null,
  }),
  actions: {
    setFailureContext(context, taskId = null) {
      this.failureContext = context
      this.failedTaskId = taskId
    },
    setProject(id, name) {
      this.projectId = id
      this.projectName = name
      localStorage.setItem('projectId', id)
      localStorage.setItem('projectName', name)
      // Reset dependent states
      this.setFunction(null, null)
      this.setTask(null)
    },
    setFunction(id, name) {
      this.functionId = id
      this.functionName = name
      if (id) {
        localStorage.setItem('functionId', id)
        localStorage.setItem('functionName', name)
      } else {
        localStorage.removeItem('functionId')
        localStorage.removeItem('functionName')
      }
      // Reset task when function changes
      this.setTask(null)
    },
    setTask(id) {
      this.taskId = id
      if (id) {
        localStorage.setItem('taskId', id)
      } else {
        localStorage.removeItem('taskId')
      }
    }
  }
})
