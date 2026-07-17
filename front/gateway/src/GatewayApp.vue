<script setup lang="ts">
import {
  Activity,
  Boxes,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Cloud,
  Ellipsis,
  Globe2,
  Network,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Route,
  Search,
  Server,
  Square,
  Trash2,
  Waypoints,
  Workflow,
} from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import GatewayEditor from './GatewayEditor.vue'
import { gatewayApi } from './gatewayApi'
import type {
  GatewayAction,
  GatewayFormData,
  GatewayItem,
  GatewayResource,
  GatewaySnapshot,
} from './types'

type Workspace = 'traffic' | 'resources' | 'activity'
type ResourceFilter = 'gateway' | 'tunnel' | 'route' | 'service'

interface ResourceView {
  kind: GatewayResource
  id: number
  title: string
  detail: string
  state: string
  tone: 'healthy' | 'idle' | 'warning' | 'danger'
  running?: boolean
  enabled: boolean
  item: GatewayItem
}

const emptySnapshot = (): GatewaySnapshot => ({ running_count: 0, total_gateways: 0, gateways: [], tunnels: [], services: [], routes: [], logs: [] })
const workspaces: Array<{ id: Workspace; label: string }> = [
  { id: 'traffic', label: '流量' },
  { id: 'resources', label: '资源' },
  { id: 'activity', label: '活动' },
]
const filters: Array<{ id: ResourceFilter; label: string }> = [
  { id: 'gateway', label: '网关' },
  { id: 'tunnel', label: '隧道' },
  { id: 'route', label: '规则' },
  { id: 'service', label: '服务' },
]

const requestedWorkspace = new URLSearchParams(window.location.search).get('view')
const requestedEditor = new URLSearchParams(window.location.search).get('edit')
const workspace = ref<Workspace>(workspaces.some((item) => item.id === requestedWorkspace) ? requestedWorkspace as Workspace : 'traffic')
const resourceFilter = ref<ResourceFilter>('gateway')
const snapshot = ref<GatewaySnapshot>(emptySnapshot())
const loading = ref(true)
const refreshing = ref(false)
const busyAction = ref('')
const error = ref('')
const notice = ref('')
const search = ref('')
const openMenu = ref('')
const editorResource = ref<GatewayResource | null>(null)
const editorItem = ref<GatewayItem | null>(null)
const saving = ref(false)
let pollTimer: ReturnType<typeof window.setInterval> | null = null
let noticeTimer: ReturnType<typeof window.setTimeout> | null = null

const runningTunnels = computed(() => snapshot.value.tunnels.filter((item) => item.running).length)
const healthy = computed(() => !snapshot.value.gateways.some((item) => item.error) && !snapshot.value.tunnels.some((item) => item.last_error))
const trafficPaths = computed(() => snapshot.value.routes.map((route) => {
  const gateway = snapshot.value.gateways.find((item) => item.id === route.gateway_id)
  const service = snapshot.value.services.find((item) => item.id === route.service_id)
  const tunnel = snapshot.value.tunnels.find((item) => item.gateway_id === route.gateway_id)
  const active = Boolean(route.enabled && service?.enabled && gateway?.running && (!tunnel || tunnel.running))
  return { route, gateway, service, tunnel, active }
}))
const issueCount = computed(() => snapshot.value.gateways.filter((item) => item.error).length + snapshot.value.tunnels.filter((item) => item.last_error).length)
const resourceCounts = computed<Record<ResourceFilter, number>>(() => ({
  gateway: snapshot.value.gateways.length,
  tunnel: snapshot.value.tunnels.length,
  route: snapshot.value.routes.length,
  service: snapshot.value.services.length,
}))
const resources = computed<ResourceView[]>(() => {
  if (resourceFilter.value === 'gateway') return snapshot.value.gateways.map((item) => ({ kind: 'gateway', id: item.id, title: item.name, detail: `${item.listen_host}:${item.listen_port} · ${item.routes_count} 条规则`, state: item.error ? '异常' : item.running ? '运行中' : item.enabled ? '已停止' : '已禁用', tone: item.error ? 'danger' : item.running ? 'healthy' : item.enabled ? 'idle' : 'warning', running: item.running, enabled: item.enabled, item }))
  if (resourceFilter.value === 'tunnel') return snapshot.value.tunnels.map((item) => ({ kind: 'tunnel', id: item.id, title: item.name, detail: item.gateway_name ? `连接 ${item.gateway_name}` : '未关联网关', state: item.last_error ? '异常' : item.running ? '已连接' : item.enabled ? '已停止' : '已禁用', tone: item.last_error ? 'danger' : item.running ? 'healthy' : item.enabled ? 'idle' : 'warning', running: item.running, enabled: item.enabled, item }))
  if (resourceFilter.value === 'route') return snapshot.value.routes.map((item) => ({ kind: 'route', id: item.id, title: item.path_prefix, detail: `${item.gateway_name} → ${item.service_name}`, state: item.enabled ? '已启用' : '已禁用', tone: item.enabled ? 'healthy' : 'warning', enabled: item.enabled, item }))
  return snapshot.value.services.map((item) => ({ kind: 'service', id: item.id, title: item.name, detail: item.target_url, state: item.enabled ? '可用' : '已禁用', tone: item.enabled ? 'healthy' : 'warning', enabled: item.enabled, item }))
})
const visibleResources = computed(() => {
  const query = search.value.trim().toLocaleLowerCase()
  return query ? resources.value.filter((item) => `${item.title} ${item.detail}`.toLocaleLowerCase().includes(query)) : resources.value
})

function messageOf(reason: unknown): string { return reason instanceof Error ? reason.message : String(reason) }
function showNotice(message: string): void {
  notice.value = message
  if (noticeTimer) window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => { notice.value = '' }, 2200)
}
async function refresh(silent = false): Promise<void> {
  if (refreshing.value) return
  refreshing.value = true
  if (!silent) error.value = ''
  try { snapshot.value = await gatewayApi.snapshot() }
  catch (reason) { if (!silent) error.value = messageOf(reason) }
  finally { refreshing.value = false; loading.value = false }
}
async function runAction(action: GatewayAction, id?: number): Promise<void> {
  if (busyAction.value) return
  busyAction.value = `${action}:${id ?? ''}`
  error.value = ''
  openMenu.value = ''
  try { snapshot.value = await gatewayApi.action(action, id); showNotice('操作已完成') }
  catch (reason) { error.value = messageOf(reason); await refresh(true) }
  finally { busyAction.value = '' }
}
function openEditor(resource: GatewayResource, item: GatewayItem | null = null): void {
  if (resource === 'route' && (!snapshot.value.gateways.length || !snapshot.value.services.length)) { error.value = '请先创建网关和服务。'; return }
  openMenu.value = ''
  editorResource.value = resource
  editorItem.value = item
}
function closeEditor(): void {
  if (!saving.value) { editorResource.value = null; editorItem.value = null }
}
async function saveEditor(data: GatewayFormData): Promise<void> {
  if (!editorResource.value) return
  saving.value = true
  error.value = ''
  try {
    snapshot.value = await gatewayApi.save(editorResource.value, data, editorItem.value?.id)
    showNotice('配置已保存')
  } catch (reason) { error.value = messageOf(reason) }
  finally { saving.value = false; if (!error.value) closeEditor() }
}
async function removeItem(view: ResourceView): Promise<void> {
  openMenu.value = ''
  if (!window.confirm(`确定删除“${view.title}”吗？`)) return
  try { snapshot.value = await gatewayApi.remove(view.kind, view.id); showNotice('配置已删除') }
  catch (reason) { error.value = messageOf(reason) }
}
function selectFilter(filter: ResourceFilter): void { resourceFilter.value = filter; search.value = ''; openMenu.value = '' }

onMounted(async () => {
  await refresh()
  if (import.meta.env.DEV && ['gateway', 'tunnel', 'route', 'service'].includes(requestedEditor || '')) openEditor(requestedEditor as GatewayResource)
  pollTimer = window.setInterval(() => { if (!document.hidden && !editorResource.value && !busyAction.value) void refresh(true) }, 3000)
})
onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
  if (noticeTimer) window.clearTimeout(noticeTimer)
})
</script>

<template>
  <div class="app-shell" @click.self="openMenu = ''">
    <header class="command-bar">
      <div class="product-mark"><span><Waypoints :size="19" /></span><div><h1>Gateway</h1><p><i :class="{ healthy }"></i>{{ healthy ? '系统正常' : `${issueCount} 项异常` }}</p></div></div>
      <div class="command-actions">
        <button class="command primary" title="启动全部网关" :disabled="Boolean(busyAction)" @click="runAction('start_all')"><Play :size="16" fill="currentColor" /><span>启动</span></button>
        <button class="command" title="停止全部网关" :disabled="Boolean(busyAction)" @click="runAction('stop_all')"><Square :size="15" fill="currentColor" /><span>停止</span></button>
        <button class="icon-button" title="刷新" aria-label="刷新" :disabled="refreshing" @click="refresh()"><RefreshCw :size="17" :class="{ spinning: refreshing }" /></button>
      </div>
    </header>

    <nav class="workspace-tabs" aria-label="网关工作区">
      <button v-for="item in workspaces" :key="item.id" :class="{ active: workspace === item.id }" @click="workspace = item.id">
        <Workflow v-if="item.id === 'traffic'" :size="15" /><Boxes v-else-if="item.id === 'resources'" :size="15" /><Activity v-else :size="15" />{{ item.label }}
      </button>
    </nav>

    <div v-if="error" class="alert-banner" role="alert"><CircleAlert :size="16" /> <span>{{ error }}</span><button title="关闭" aria-label="关闭" @click="error = ''">×</button></div>
    <main class="workspace" :aria-busy="loading || refreshing">
      <div v-if="loading" class="loading-state"><RefreshCw :size="20" class="spinning" />正在连接</div>

      <template v-else-if="workspace === 'traffic'">
        <section class="health-strip" aria-label="网关摘要">
          <div><span>网关</span><strong>{{ snapshot.running_count }}<small>/{{ snapshot.total_gateways }}</small></strong></div>
          <div><span>隧道</span><strong>{{ runningTunnels }}<small>/{{ snapshot.tunnels.length }}</small></strong></div>
          <div><span>流量路径</span><strong>{{ trafficPaths.length }}</strong></div>
          <div :class="{ attention: issueCount }"><span>异常</span><strong>{{ issueCount }}</strong></div>
        </section>

        <section class="traffic-section">
          <header class="section-title"><div><h2>流量路径</h2><p>入口到上游的实时链路</p></div><button class="icon-button" title="添加分发规则" aria-label="添加分发规则" @click="openEditor('route')"><Plus :size="18" /></button></header>
          <div v-if="trafficPaths.length" class="path-list">
            <article v-for="path in trafficPaths" :key="path.route.id" class="path-row">
              <div class="path-summary"><span class="path-state" :class="{ active: path.active }"><CheckCircle2 v-if="path.active" :size="15" /><CircleAlert v-else :size="15" /></span><code>{{ path.route.path_prefix }}</code><span>{{ path.active ? '在线' : '未连通' }}</span><button class="icon-button small" title="编辑路径" aria-label="编辑路径" @click="openEditor('route', path.route)"><Pencil :size="14" /></button></div>
              <div class="path-flow">
                <div class="flow-node"><Globe2 :size="16" /><span><small>入口</small><b>{{ path.tunnel?.name || '本地访问' }}</b></span></div><ChevronRight :size="15" />
                <div class="flow-node"><Network :size="16" /><span><small>网关</small><b>{{ path.gateway ? `${path.gateway.name} · ${path.gateway.listen_port}` : '网关缺失' }}</b></span></div><ChevronRight :size="15" />
                <div class="flow-node"><Server :size="16" /><span><small>上游</small><b>{{ path.service?.name || '服务缺失' }}</b></span></div>
              </div>
            </article>
          </div>
          <div v-else class="empty-state"><Route :size="24" /><strong>还没有流量路径</strong><button class="primary" @click="openEditor('route')"><Plus :size="16" />添加规则</button></div>
        </section>

        <section v-if="issueCount" class="traffic-section">
          <header class="section-title"><div><h2>需要处理</h2><p>影响连通性的运行错误</p></div></header>
          <div class="issue-list">
            <div v-for="item in snapshot.gateways.filter((gateway) => gateway.error)" :key="`g-${item.id}`"><CircleAlert :size="16" /><span><strong>{{ item.name }}</strong><small>{{ item.error }}</small></span><button @click="openEditor('gateway', item)">检查</button></div>
            <div v-for="item in snapshot.tunnels.filter((tunnel) => tunnel.last_error)" :key="`t-${item.id}`"><CircleAlert :size="16" /><span><strong>{{ item.name }}</strong><small>{{ item.last_error }}</small></span><button @click="openEditor('tunnel', item)">检查</button></div>
          </div>
        </section>
      </template>

      <template v-else-if="workspace === 'resources'">
        <section class="resource-toolbar">
          <div class="resource-filters">
            <button v-for="filter in filters" :key="filter.id" :class="{ active: resourceFilter === filter.id }" @click="selectFilter(filter.id)">{{ filter.label }}<span>{{ resourceCounts[filter.id] }}</span></button>
          </div>
          <div class="resource-tools"><label class="search-box"><Search :size="15" /><input v-model="search" aria-label="搜索资源" placeholder="搜索" /></label><button class="primary icon-button" title="添加资源" aria-label="添加资源" @click="openEditor(resourceFilter)"><Plus :size="18" /></button></div>
        </section>

        <section class="resource-list">
          <article v-for="view in visibleResources" :key="`${view.kind}-${view.id}`" class="resource-row">
            <span class="resource-icon"><Network v-if="view.kind === 'gateway'" :size="18" /><Cloud v-else-if="view.kind === 'tunnel'" :size="18" /><Route v-else-if="view.kind === 'route'" :size="18" /><Server v-else :size="18" /></span>
            <div class="resource-identity"><strong>{{ view.title }}</strong><span>{{ view.detail }}</span></div>
            <span class="status-pill" :class="view.tone"><i></i>{{ view.state }}</span>
            <button v-if="view.kind === 'gateway' || view.kind === 'tunnel'" class="icon-button" :title="view.running ? '停止' : '启动'" :aria-label="view.running ? '停止' : '启动'" :disabled="Boolean(busyAction) || (!view.enabled && !view.running)" @click="runAction(`${view.running ? 'stop' : 'start'}_${view.kind}` as GatewayAction, view.id)"><Square v-if="view.running" :size="14" fill="currentColor" /><Play v-else :size="15" fill="currentColor" /></button>
            <div class="menu-anchor"><button class="icon-button" title="更多操作" aria-label="更多操作" @click.stop="openMenu = openMenu === `${view.kind}-${view.id}` ? '' : `${view.kind}-${view.id}`"><Ellipsis :size="18" /></button><div v-if="openMenu === `${view.kind}-${view.id}`" class="row-menu"><button @click="openEditor(view.kind, view.item)"><Pencil :size="15" />编辑</button><button class="danger" @click="removeItem(view)"><Trash2 :size="15" />删除</button></div></div>
          </article>
          <div v-if="!visibleResources.length" class="empty-state"><Boxes :size="24" /><strong>{{ search ? '没有匹配的资源' : '暂无资源' }}</strong></div>
        </section>
      </template>

      <template v-else>
        <section class="activity-head"><div><h2>运行活动</h2><p>最近的网关请求与运行事件</p></div><span><Activity :size="15" />{{ snapshot.logs.length }} 条</span></section>
        <section v-if="snapshot.logs.length" class="activity-list">
          <article v-for="(entry, index) in snapshot.logs" :key="`${entry.time}-${index}`" :class="entry.level"><time>{{ entry.time }}</time><span class="activity-marker"></span><div><strong>{{ entry.level === 'error' ? '错误' : entry.level === 'warning' ? '警告' : '信息' }}</strong><p>{{ entry.message }}</p></div></article>
        </section>
        <div v-else class="empty-state"><Activity :size="24" /><strong>暂无运行活动</strong></div>
      </template>
    </main>

    <div v-if="notice" class="toast" role="status"><CheckCircle2 :size="16" />{{ notice }}</div>
    <GatewayEditor v-if="editorResource" :resource="editorResource" :item="editorItem" :snapshot="snapshot" :saving="saving" @close="closeEditor" @save="saveEditor" />
  </div>
</template>
