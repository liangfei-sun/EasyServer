import { createRouter, createWebHashHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import Services from '../views/Services.vue'
import Market from '../views/Market.vue'
import Settings from '../views/Settings.vue'
import SetupWizard from '../views/SetupWizard.vue'
import Docs from '../views/Docs.vue'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', component: Dashboard },
  { path: '/services', component: Services },
  { path: '/market', component: Market },
  { path: '/settings', component: Settings },
  { path: '/setup', component: SetupWizard },
  { path: '/docs', component: Docs },
  { path: '/docs/:docId', component: Docs, props: true }
]

export default createRouter({
  history: createWebHashHistory(),
  routes
})
