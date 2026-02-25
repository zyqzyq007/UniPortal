import { createRouter, createWebHistory } from 'vue-router'
import LoginPage from '../pages/auth/Login.vue'
import ProjectsList from '../pages/projects/ProjectsList.vue'
import ProjectHome from '../pages/projects/ProjectHome.vue'
import ToolsCenter from '../pages/tools/ToolsCenter.vue'
import TasksList from '../pages/tasks/TasksList.vue'
import TaskDetail from '../pages/tasks/TaskDetail.vue'
import ResultView from '../pages/result/ResultView.vue'
import ForbiddenPage from '../pages/errors/Forbidden.vue'
import NotFoundPage from '../pages/errors/NotFound.vue'
import DefaultLayout from '../layouts/DefaultLayout.vue'
import ProjectsUpload from '../pages/projects/ProjectsUpload.vue'
import ToolViewer from '../pages/tools/ToolViewer.vue'
import UserProfile from '../pages/user/UserProfile.vue'
import { getToken } from '../utils/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/projects' },
    { path: '/login', name: 'Login', component: LoginPage },
    { path: '/forbidden', name: 'Forbidden', component: ForbiddenPage },
    {
      path: '/projects',
      name: 'Projects',
      component: ProjectsList,
      meta: { requiresAuth: true }
    },
    {
      path: '/projects/upload',
      name: 'ProjectsUpload',
      component: ProjectsUpload,
      meta: { requiresAuth: true }
    },
    {
      path: '/profile',
      name: 'UserProfile',
      component: UserProfile,
      meta: { requiresAuth: true }
    },
    {
      path: '/projects/:projectId',
      component: DefaultLayout,
      meta: { requiresAuth: true },
      children: [
        { path: '', name: 'ProjectHome', component: ProjectHome },
        { path: 'tools', name: 'ToolsCenter', component: ToolsCenter },
        { path: 'tools/:toolKey', name: 'ToolViewer', component: ToolViewer },
        { path: 'tasks', name: 'TasksList', component: TasksList },
        { path: 'tasks/:taskId', name: 'TaskDetail', component: TaskDetail },
        { path: 'results/:taskId', name: 'ResultView', component: ResultView }
      ]
    },
    { path: '/:pathMatch(.*)*', name: 'NotFound', component: NotFoundPage }
  ]
})

router.beforeEach((to) => {
  const requiresAuth = to.matched.some((record) => record.meta.requiresAuth)
  if (!requiresAuth) {
    return true
  }
  if (getToken()) {
    return true
  }
  return { name: 'Login', query: { redirect: to.fullPath } }
})

export default router
