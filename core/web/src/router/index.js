import { createRouter, createWebHashHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import Services from '../views/Services.vue'
import Market from '../views/Market.vue'
import Settings from '../views/Settings.vue'
import SetupWizard from '../views/SetupWizard.vue'
import Login from '../views/Login.vue'
import NetworkConfig from '../views/NetworkConfig.vue'
import Backup from '../views/Backup.vue'
import Docs from '../views/Docs.vue'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', component: Dashboard },
  { path: '/services', component: Services },
  { path: '/network', component: NetworkConfig },
  { path: '/market', component: Market },
  { path: '/backup', component: Backup },
  { path: '/settings', component: Settings },
  { path: '/setup', component: SetupWizard },
  { path: '/login', component: Login },
  { path: '/network-guide', redirect: '/network' },
  { path: '/tunnel', redirect: '/network' },
  { path: '/docs', component: Docs },
  { path: '/docs/:docId', component: Docs, props: true }
]

export default createRouter({
  history: createWebHashHistory(),
  routes
})
