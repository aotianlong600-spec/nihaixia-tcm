<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { api } from './api'
import Clinic from './Clinic.vue'
import Knowledge from './Knowledge.vue'
import Rules from './Rules.vue'
import Settings from './Settings.vue'
const tab = ref('clinic')
const views = {clinic:Clinic,knowledge:Knowledge,rules:Rules,settings:Settings}
const view = computed(()=>views[tab.value as keyof typeof views])
const connected = ref(false)
const error = ref('')
const overview = ref<Record<string,number>>({})
async function connect() {
  error.value = ''
  try { await api.session(); overview.value = await api.request('/overview'); connected.value = true }
  catch(e) { connected.value=false; error.value = e instanceof Error ? e.message : String(e) }
}
onMounted(connect)
</script>
<template>
  <div class="shell">
    <aside class="sidebar"><div class="brand"><span class="brand-symbol">研</span><div>辨证研究<small>医师工作台</small></div></div>
      <nav aria-label="工作台导航"><button v-for="item in [{id:'clinic',label:'接诊与复诊',hint:'01'},{id:'knowledge',label:'资料与溯源',hint:'02'},{id:'rules',label:'规则审核',hint:'03'},{id:'settings',label:'模型与备份',hint:'04'}]" :key="item.id" :class="{active:tab===item.id}" @click="tab=item.id"><span>{{item.hint}}</span>{{item.label}}</button></nav>
      <div class="sidebar-note">证据先行，逐项核实。<br>规则结果与医生决定独立留存。</div><span class="connection">{{connected?'● 本地服务已连接':'○ 本地服务未连接'}}</span>
    </aside>
    <main><header class="topbar"><div><small>本地研究空间 / {{tab==='clinic'?'接诊与复诊':tab==='knowledge'?'资料与溯源':tab==='rules'?'规则审核':'系统设置'}}</small><h1>{{tab==='clinic'?'当次事实，逐证比较':tab==='knowledge'?'回到原文，核对证据':tab==='rules'?'让每条规则有据可审':'控制外发，保留恢复能力'}}</h1></div><el-tag type="warning" size="large">工程验证 · 模拟病例</el-tag></header>
      <div class="mode-banner">仅用于工程与合成病例验证。真实规则须经文本、语义及临床三级人工专业审核；规则条件匹配不等于诊断确证。</div>
      <div v-if="error" class="error-box" role="alert">连接失败：{{error}} <el-button size="small" @click="connect">重试</el-button></div>
      <div class="stats"><span>资料 <b>{{overview.documents ?? '—'}}</b></span><span>物理页 <b>{{overview.pages ?? '—'}}</b></span><span>临床规则发布 <b>{{overview.clinical_published_rules ?? '—'}}</b></span><span>方证研究条目 <b>{{overview.research_entries ?? '—'}}</b></span><span>模拟访次 <b>{{overview.visits ?? '—'}}</b></span><el-button text @click="connect">刷新状态</el-button></div>
      <KeepAlive><component :is="view" :key="tab" v-if="connected" /></KeepAlive>
      <div v-if="!connected" class="empty panel">请先启动本地 API 服务。工作台不会生成模拟接口结果。</div>
      <footer>所有输出供医师研究核对 · 风险核查的“未命中”只在已覆盖范围内有效</footer>
    </main>
  </div>
</template>
