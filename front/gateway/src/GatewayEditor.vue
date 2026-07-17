<script setup lang="ts">
import { Save, X } from '@lucide/vue'
import { computed, ref } from 'vue'
import type {
  GatewayFormData,
  GatewayItem,
  GatewayResource,
  GatewaySnapshot,
} from './types'

const props = defineProps<{
  resource: GatewayResource
  item: GatewayItem | null
  snapshot: GatewaySnapshot
  saving: boolean
}>()
const emit = defineEmits<{
  close: []
  save: [data: GatewayFormData]
}>()

const labels: Record<GatewayResource, string> = {
  service: '服务',
  gateway: '本地网关',
  route: '分发规则',
  tunnel: 'Cloudflare Tunnel',
}
const title = computed(() => `${props.item ? '编辑' : '添加'}${labels[props.resource]}`)

function initialData(): GatewayFormData {
  if (props.item) {
    const data = { ...props.item } as GatewayFormData
    if (props.resource === 'tunnel') data.token = ''
    return data
  }
  if (props.resource === 'service') return { name: '', target_url: '', enabled: true, remarks: '' }
  if (props.resource === 'gateway') return { name: '', listen_host: '127.0.0.1', listen_port: 8080, enabled: true, auto_start: false, remarks: '' }
  if (props.resource === 'route') return { gateway_id: props.snapshot.gateways[0]?.id, service_id: props.snapshot.services[0]?.id, path_prefix: '/', preserve_host: false, enabled: true }
  return { name: '', cloudflared_path: 'cloudflared', token: '', gateway_id: props.snapshot.gateways[0]?.id ?? null, enabled: true, auto_start: false, remarks: '' }
}

const form = ref(initialData())

function submit(): void {
  emit('save', { ...form.value })
}
</script>

<template>
  <div class="drawer-backdrop" @mousedown.self="emit('close')">
    <form class="editor-drawer" @submit.prevent="submit">
      <header class="editor-head">
        <div><span>{{ item ? '编辑配置' : '新建配置' }}</span><h2>{{ title }}</h2></div>
        <button class="icon-button" type="button" title="关闭" aria-label="关闭" @click="emit('close')"><X :size="18" /></button>
      </header>

      <div class="form-body"><div class="form-grid" v-if="resource === 'service'">
        <label>名称<input v-model.trim="form.name" required /></label>
        <label>目标地址<input v-model.trim="form.target_url" type="url" placeholder="http://127.0.0.1:6694" required /></label>
        <label class="wide">备注<input v-model.trim="form.remarks" /></label>
        <label class="check wide"><input v-model="form.enabled" type="checkbox" />启用</label>
      </div>

      <div class="form-grid" v-else-if="resource === 'gateway'">
        <label>名称<input v-model.trim="form.name" required /></label>
        <label>监听地址<input v-model.trim="form.listen_host" required /></label>
        <label>监听端口<input v-model.number="form.listen_port" type="number" min="1" max="65535" required /></label>
        <label class="wide">备注<input v-model.trim="form.remarks" /></label>
        <label class="check"><input v-model="form.enabled" type="checkbox" />启用</label>
        <label class="check"><input v-model="form.auto_start" type="checkbox" />自动启动</label>
      </div>

      <div class="form-grid" v-else-if="resource === 'route'">
        <label>网关<select v-model.number="form.gateway_id" required><option v-for="gateway in snapshot.gateways" :key="gateway.id" :value="gateway.id">{{ gateway.name }} · {{ gateway.listen_port }}</option></select></label>
        <label>服务<select v-model.number="form.service_id" required><option v-for="service in snapshot.services" :key="service.id" :value="service.id">{{ service.name }}</option></select></label>
        <label class="wide">路径前缀<input v-model.trim="form.path_prefix" placeholder="/api" required /></label>
        <label class="check"><input v-model="form.preserve_host" type="checkbox" />保留客户端 Host</label>
        <label class="check"><input v-model="form.enabled" type="checkbox" />启用</label>
      </div>

      <div class="form-grid" v-else>
        <label>名称<input v-model.trim="form.name" required /></label>
        <label>cloudflared<input v-model.trim="form.cloudflared_path" required /></label>
        <label class="wide">Token<input v-model.trim="form.token" type="password" :required="!item" :placeholder="item ? '留空则保留现有 Token' : 'Cloudflare Tunnel Token'" /></label>
        <label>关联网关<select v-model="form.gateway_id"><option :value="null">不关联</option><option v-for="gateway in snapshot.gateways" :key="gateway.id" :value="gateway.id">{{ gateway.name }} · {{ gateway.listen_port }}</option></select></label>
        <label>备注<input v-model.trim="form.remarks" /></label>
        <label class="check"><input v-model="form.enabled" type="checkbox" />启用</label>
        <label class="check"><input v-model="form.auto_start" type="checkbox" />自动启动</label>
      </div></div>

      <footer class="editor-actions">
        <button type="button" @click="emit('close')">取消</button>
        <button class="primary" type="submit" :disabled="saving"><Save :size="15" />{{ saving ? '保存中…' : '保存' }}</button>
      </footer>
    </form>
  </div>
</template>
