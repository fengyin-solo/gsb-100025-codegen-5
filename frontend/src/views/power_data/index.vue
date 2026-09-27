<template>
  <section class="page" data-module="power_data">
    <header class="page-head">
      <div>
        <h2>发电监测管理</h2>
        <p class="page-desc">
          发电记录先进入采集核对队列：电站和小时形成一行，缺组件温度或环境温度的行停在校验区，
          由值班员逐条补录；通过校验后才写入正式记录，并生成可另存的表格文件。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="focusIntake">登记发电记录</button>
        <button class="btn" type="button" @click="exportRows">导出发电监测清单</button>
      </div>
    </header>

    <section class="queue-panel">
      <h3 class="panel-title">采集核对队列</h3>

      <div class="stat-row">
        <article v-for="item in queueStats" :key="item.label" class="stat-card">
          <span class="stat-label">{{ item.label }}</span>
          <strong class="stat-value">{{ item.value }}</strong>
        </article>
      </div>

      <form ref="intakeRef" class="filter-bar intake-bar" @submit.prevent="submitIntake">
        <label v-for="field in intakeFields" :key="field.name" class="filter-item">
          <span>{{ field.name }}<em v-if="field.required" class="required">*</em></span>
          <input v-model="intakeForm[field.name]" :placeholder="field.placeholder" />
        </label>
        <button class="btn primary" type="submit">进入核对队列</button>
      </form>

      <div class="filter-bar">
        <label class="filter-item">
          <span>核对状态</span>
          <select v-model="queueFilters.status">
            <option value="">全部</option>
            <option v-for="item in queueStatuses" :key="item" :value="item">{{ item }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>电站编号</span>
          <input v-model="queueFilters.station" placeholder="按电站编号过滤" />
        </label>
        <button class="btn" type="button" @click="loadQueue">查询</button>
        <button class="btn ghost" type="button" @click="exportQueue">导出队列模板</button>
        <button class="btn primary" type="button" @click="commitQueue">写入正式记录并生成表格</button>
      </div>

      <table class="data-table">
        <thead>
          <tr>
            <th>电站编号</th>
            <th>小时</th>
            <th>发电量</th>
            <th>辐照度</th>
            <th>组件温度</th>
            <th>环境温度</th>
            <th>核对状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="row in queueRows" :key="String(row.id)">
            <tr :class="{ 'row-hold': row.status === '待补录' }">
              <td>{{ row['电站编号'] }}</td>
              <td>{{ row['小时'] }}</td>
              <td>{{ row['发电量'] ?? '—' }}</td>
              <td>{{ row['辐照度'] ?? '—' }}</td>
              <td><span :class="tempTagClass(row, '组件温度')">{{ tempLabel(row, '组件温度') }}</span></td>
              <td><span :class="tempTagClass(row, '环境温度')">{{ tempLabel(row, '环境温度') }}</span></td>
              <td><span class="tag" :class="statusTagClass(String(row.status))">{{ row.status }}</span></td>
              <td class="row-actions">
                <button
                  v-if="row.status === '待补录' || row.status === '待核对'"
                  class="link"
                  type="button"
                  @click="openSupplement(row)"
                >
                  补录
                </button>
                <button
                  v-if="row.status === '待核对'"
                  class="link"
                  type="button"
                  @click="validateRow(row)"
                >
                  校验通过
                </button>
                <span v-if="row.status === '已通过'" class="muted-text">待入库</span>
                <span v-if="row.status === '已入库'" class="muted-text">{{ row['入库记录编号'] }}</span>
              </td>
            </tr>
            <tr v-if="supplementFor === Number(row.id)" class="supplement-row">
              <td colspan="8">
                <form class="supplement-form" @submit.prevent="submitSupplement(row)">
                  <label>
                    组件温度
                    <input v-model="supplementForm['组件温度']" placeholder="补录组件温度" />
                  </label>
                  <label class="check">
                    <input v-model="supplementForm['组件温度零值确认']" type="checkbox" />
                    人工确认零值
                  </label>
                  <label>
                    环境温度
                    <input v-model="supplementForm['环境温度']" placeholder="补录环境温度" />
                  </label>
                  <label class="check">
                    <input v-model="supplementForm['环境温度零值确认']" type="checkbox" />
                    人工确认零值
                  </label>
                  <label>
                    补录人
                    <input v-model="supplementForm['补录人']" />
                  </label>
                  <button class="btn primary" type="submit">提交补录</button>
                  <button class="btn ghost" type="button" @click="supplementFor = null">取消</button>
                </form>
              </td>
            </tr>
          </template>
          <tr v-if="!queueRows.length">
            <td colspan="8" class="empty-state">队列暂无数据，可先登记采集；空范围导出仍会保留模板表头</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>队列共 {{ queueTotal }} 行</span>
        <span v-if="commitFile" class="ok-text">
          已生成表格文件：<a :href="commitFile.url" target="_blank">{{ commitFile.name }}</a>（点击另存）
        </span>
        <span v-if="noticeMessage" class="ok-text">{{ noticeMessage }}</span>
        <span v-if="queueMessage" class="error-text">{{ queueMessage }}</span>
      </footer>
    </section>

    <section class="records-panel">
      <h3 class="panel-title">正式发电记录</h3>

      <form class="filter-bar" @submit.prevent="reload">
        <label v-for="field in filterFields" :key="field" class="filter-item">
          <span>{{ field }}</span>
          <input v-model="filters[field]" :placeholder="`按${field}检索`" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column">{{ column }}</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="String(row.id)">
            <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
            <td class="row-actions">
              <button
                v-for="action in actions"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td :colspan="columns.length + 1" class="empty-state">暂无正式发电记录，需先通过采集核对队列入库</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>共 {{ total }} 条发电监测记录</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, any>

const ENDPOINT = '/api/power_data'
const API_BASE = import.meta.env.VITE_API_BASE ?? ''
const session = useSessionStore()

const columns = ["记录编号", "电站编号", "发电量", "辐照度", "组件温度", "环境温度", "记录时间", "数据状态"]
const actions = ["标记偏低", "确认异常", "数据补录"]
const queueStatuses = ["待补录", "待核对", "已通过", "已入库"]

// ---- 正式记录 ----
const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

// ---- 采集核对队列 ----
const queueRows = ref<Row[]>([])
const queueTotal = ref(0)
const queueSummary = ref<Record<string, number>>({})
const queueMessage = ref('')
const noticeMessage = ref('')
const queueFilters = ref({ status: '', station: '' })
const commitFile = ref<{ name: string; url: string } | null>(null)

const queueStats = computed(() => [
  { label: '校验区（待补录）', value: queueSummary.value['待补录'] ?? 0 },
  { label: '待核对', value: queueSummary.value['待核对'] ?? 0 },
  { label: '已通过', value: queueSummary.value['已通过'] ?? 0 },
  { label: '已入库', value: queueSummary.value['已入库'] ?? 0 },
])

const intakeRef = ref<HTMLElement | null>(null)
const intakeFields = [
  { name: '电站编号', required: true, placeholder: '如 PLAN-0001' },
  { name: '小时', required: true, placeholder: '如 2026-09-27 08:00' },
  { name: '发电量', required: false, placeholder: 'kWh，可留空' },
  { name: '辐照度', required: false, placeholder: 'W/㎡，可留空' },
  { name: '组件温度', required: false, placeholder: '℃，缺测则停校验区' },
  { name: '环境温度', required: false, placeholder: '℃，缺测则停校验区' },
]
const intakeForm = ref<Record<string, string>>({
  电站编号: '', 小时: '', 发电量: '', 辐照度: '', 组件温度: '', 环境温度: '',
})

const supplementFor = ref<number | null>(null)
const supplementForm = ref({
  组件温度: '',
  环境温度: '',
  组件温度零值确认: false,
  环境温度零值确认: false,
  补录人: session.operator,
})

function tempState(row: Row, field: string): string {
  return row['温度口径']?.[field] ?? '未采集'
}

function tempLabel(row: Row, field: string): string {
  const state = tempState(row, field)
  if (state === '未采集') return '未采集'
  if (state === '零值待确认') return '0（零值待确认）'
  if (state === '人工零值') return '0（人工零值）'
  return String(row[field] ?? '—')
}

function tempTagClass(row: Row, field: string): string {
  const state = tempState(row, field)
  if (state === '未采集') return 'tag blank'
  if (state === '零值待确认') return 'tag pending-zero'
  if (state === '人工零值') return 'tag zero'
  return ''
}

function statusTagClass(status: string): string {
  if (status === '待补录') return 'hold'
  if (status === '待核对') return 'ready'
  if (status === '已通过') return 'ok'
  return 'done'
}

function focusIntake() {
  intakeRef.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

async function loadQueue() {
  queueMessage.value = ''
  const query = new URLSearchParams()
  if (queueFilters.value.status) query.set('status', queueFilters.value.status)
  if (queueFilters.value.station) query.set('station', queueFilters.value.station)
  try {
    const response = await request(`${ENDPOINT}/queue?${query.toString()}`)
    if (!response.ok) {
      throw new Error('采集核对队列读取失败')
    }
    const payload = await response.json()
    queueRows.value = payload.items ?? []
    queueTotal.value = payload.total ?? 0
    queueSummary.value = payload.summary ?? {}
  } catch (error) {
    queueMessage.value = error instanceof Error ? error.message : '采集核对队列读取失败'
  }
}

async function submitIntake() {
  queueMessage.value = ''
  noticeMessage.value = ''
  commitFile.value = null
  const values: Record<string, string> = {}
  for (const [key, value] of Object.entries(intakeForm.value)) {
    if (String(value).trim() !== '') values[key] = String(value).trim()
  }
  try {
    const response = await request(`${ENDPOINT}/queue/intake`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      queueMessage.value = payload.message || '采集进队未生效'
      return
    }
    noticeMessage.value = payload.message
    intakeForm.value = { 电站编号: '', 小时: '', 发电量: '', 辐照度: '', 组件温度: '', 环境温度: '' }
    await loadQueue()
  } catch (error) {
    queueMessage.value = error instanceof Error ? error.message : '采集进队失败'
  }
}

function openSupplement(row: Row) {
  const id = Number(row.id)
  if (supplementFor.value === id) {
    supplementFor.value = null
    return
  }
  supplementFor.value = id
  supplementForm.value = {
    组件温度: tempState(row, '组件温度') === '未采集' ? '' : String(row['组件温度'] ?? ''),
    环境温度: tempState(row, '环境温度') === '未采集' ? '' : String(row['环境温度'] ?? ''),
    组件温度零值确认: Boolean(row['组件温度零值确认']),
    环境温度零值确认: Boolean(row['环境温度零值确认']),
    补录人: session.operator,
  }
}

async function submitSupplement(row: Row) {
  queueMessage.value = ''
  noticeMessage.value = ''
  const values: Record<string, string | boolean> = {
    组件温度零值确认: supplementForm.value['组件温度零值确认'],
    环境温度零值确认: supplementForm.value['环境温度零值确认'],
    补录人: supplementForm.value['补录人'],
  }
  if (supplementForm.value['组件温度'].trim() !== '') values['组件温度'] = supplementForm.value['组件温度'].trim()
  if (supplementForm.value['环境温度'].trim() !== '') values['环境温度'] = supplementForm.value['环境温度'].trim()
  try {
    const response = await request(`${ENDPOINT}/queue/${row.id}/supplement`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      queueMessage.value = payload.message || '补录未生效'
      return
    }
    noticeMessage.value = payload.message
    supplementFor.value = null
    await loadQueue()
  } catch (error) {
    queueMessage.value = error instanceof Error ? error.message : '补录失败'
  }
}

async function validateRow(row: Row) {
  queueMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/queue/${row.id}/validate`, {
      method: 'POST',
      body: JSON.stringify({ values: {} }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      queueMessage.value = payload.message || '校验未通过'
      return
    }
    noticeMessage.value = payload.message
    await loadQueue()
  } catch (error) {
    queueMessage.value = error instanceof Error ? error.message : '校验失败'
  }
}

async function commitQueue() {
  queueMessage.value = ''
  noticeMessage.value = ''
  commitFile.value = null
  try {
    const response = await request(`${ENDPOINT}/queue/commit`, {
      method: 'POST',
      body: JSON.stringify({ values: {} }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      queueMessage.value = payload.message || '入库未生效'
      return
    }
    noticeMessage.value = payload.message
    commitFile.value = { name: payload.entry.file, url: `${API_BASE}${payload.entry.url}` }
    await Promise.all([loadQueue(), reload()])
  } catch (error) {
    queueMessage.value = error instanceof Error ? error.message : '入库失败'
  }
}

function exportQueue() {
  const query = new URLSearchParams()
  if (queueFilters.value.status) query.set('status', queueFilters.value.status)
  if (queueFilters.value.station) query.set('station', queueFilters.value.station)
  window.open(`${API_BASE}${ENDPOINT}/queue/export?${query.toString()}`, '_blank')
}

// ---- 正式记录 ----

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${API_BASE}${ENDPOINT}/export`, '_blank')
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '发电监测动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '发电监测操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('发电记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '发电监测列表读取失败'
  }
}

onMounted(() => {
  void loadQueue()
  void reload()
})
</script>

<style scoped>
.panel-title { margin: 18px 0 8px; font-size: 15px; }
.intake-bar { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.filter-item input, .filter-item select { padding: 4px 8px; border: 1px solid var(--border); border-radius: 4px; }
.required { color: #b42318; font-style: normal; }
.tag { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; background: #eef2f7; color: #475569; }
.tag.blank { background: #fef3f2; color: #b42318; }
.tag.pending-zero { background: #fffaeb; color: #b54708; }
.tag.zero { background: #ecfdf3; color: #067647; }
.tag.hold { background: #fef3f2; color: #b42318; }
.tag.ready { background: #eff8ff; color: #175cd3; }
.tag.ok { background: #ecfdf3; color: #067647; }
.tag.done { background: #f4f3ff; color: #5925dc; }
.row-hold td { background: #fffaf5; }
.supplement-row td { background: #f8fafc; }
.supplement-form { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; font-size: 13px; }
.supplement-form input:not([type='checkbox']) { padding: 4px 8px; border: 1px solid var(--border); border-radius: 4px; }
.check { display: inline-flex; gap: 4px; align-items: center; color: var(--muted); }
.muted-text { color: var(--muted); font-size: 12px; }
.ok-text { color: #067647; }
</style>
