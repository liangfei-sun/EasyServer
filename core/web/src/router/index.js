import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import Services from '../views/Services.vue'
import Market from '../views/Market.vue'
import Settings from '../views/Settings.vue'
import SetupWizard from '../views/SetupWizard.vue'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', component: Dashboard },
  { path: '/services', component: Services },
  { path: '/market', component: Market },
  { path: '/settings', component: Settings },
  { path: '/setup', component: SetupWizard }
]

export default createRouter({
  history: createWebHistory(),
  routes
})
