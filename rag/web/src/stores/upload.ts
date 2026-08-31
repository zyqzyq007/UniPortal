import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useUploadStore = defineStore('upload', () => {
  const isUploading = ref(false)

  function setUploading(value: boolean) {
    isUploading.value = value
  }

  return { isUploading, setUploading }
})
