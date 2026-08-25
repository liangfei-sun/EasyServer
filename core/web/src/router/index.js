import { createRouter, createWebHashHistory } from 'vue-router'

const Dashboard = () => import('../views/Dashboard.vue')
const Services = () => import('../views/Services.vue')
const Market = () => import('../views/Market.vue')
const Settings = () => import('../views/Settings.vue')
const SetupWizard = () => import('../views/SetupWizard.vue')
const Login = () => import('../views/Login.vue')
const NetworkConfig = () => import('../views/NetworkConfig.vue')
const Backup = () => import('../views/Backup.vue')
const Docs = () => import('../views/Docs.vue')

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
