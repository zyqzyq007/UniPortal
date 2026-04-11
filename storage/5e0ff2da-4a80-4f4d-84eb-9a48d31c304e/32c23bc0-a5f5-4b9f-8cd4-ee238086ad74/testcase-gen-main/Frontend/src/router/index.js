import { createRouter, createWebHistory } from 'vue-router'
import UploadView from '../views/UploadView.vue'
import BrowseView from '../views/BrowseView.vue'
import GenerateView from '../views/GenerateView.vue'
import ResultView from '../views/ResultView.vue'
import ResultDashboardView from '../views/ResultDashboardView.vue'
import { useAppStore } from '../store'

const routes = [
  {
    path: '/',
    name: 'upload',
    component: UploadView,
  },
  {
    path: '/browse',
    name: 'browse',
    component: BrowseView,
    beforeEnter: (to, from, next) => {
      const store = useAppStore()
      if (!store.projectId) next('/')
      else next()
    }
  },
  {
    path: '/generate',
    name: 'generate',
    component: GenerateView,
    beforeEnter: (to, from, next) => {
      const store = useAppStore()
      if (!store.projectId) next('/')
      else if (!store.functionId) next('/browse')
      else next()
    }
  },
  {
    path: '/result',
    name: 'result',
    component: ResultView,
    beforeEnter: (to, from, next) => {
      const store = useAppStore()
      if (!store.taskId) next('/')
      else next()
    }
  },
  {
    path: '/dashboard',
    name: 'dashboard',
    component: ResultDashboardView,
    beforeEnter: (to, from, next) => {
      const store = useAppStore()
      if (!store.projectId) next('/')
      else next()
    }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
