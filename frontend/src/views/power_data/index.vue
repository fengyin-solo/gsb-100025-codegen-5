<template>
  <section class="page" data-module="power_data">
    <header class="page-head">
      <div>
        <h2>发电量监测</h2>
        <p class="page-desc">发电记录先进入采集核对队列：电站与小时形成一行；缺少组件温度或环境温度的行停在校验区，由值班员逐条补录，通过后才写入正式记录，可另存表格文件。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" :class="{ primary: tab === 'formal' }" @click="switchTab('formal')">正式发电记录</button>
        <button class="btn" type="button" :class="{ primary: tab === 'queue' }" @click="switchTab('queue')">采集核对队列</button>
      </div>
    </header>

    <!-- ============ 采集核对队列 ============ -->
    <template v-if="tab === 'queue'">
      <div class="stat-row">
        <article v-for="item in queueStats" :key="item.label" class="stat-card" :class="item.tone">
          <span class="stat-label">{{ item.label }}</span>
          <strong class="stat-value">{{ item.value }}</strong>
        </article>
      </div>

      <form class="filter-bar" @submit.prevent="loadQueue">
        <label class="filter-item">
          <span>日期</span>
          <input v-model="queueFilters.date" placeholder="YYYY-MM-DD（空范围仍保留模板）" />
        </label>
        <label class="filter-item">
          <span>电站编号</span>
          <input v-model="queueFilters.station" placeholder="按电站编号检索，可留空" />
        </label>
        <label class="filter-item">
          <span>队列状态</span>
          <select v-model="queueFilters.status">
            <option value="">全部</option>
            <option v-for="status in queueStatuses" :key="status" :value="status">{{ status }}</option>
          </select>
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetQueueFilters">重置条件</button>
        <button class="btn primary" type="button" @click="showCollectForm = !showCollectForm">模拟采集入队</button>
        <button class="btn primary" type="button" @click="commitQueue">校验通过 · 写入正式记录</button>
      </form>

      <form v-if="showCollectForm" class="collect-panel" @submit.prevent="runCollect">
        <label class="filter-item">
          <span>采集日期</span>
          <input v-model="collectForm.date" placeholder="YYYY-MM-DD" required />
        </label>
        <label class="filter-item">
          <span>电站编号（留空=全部电站）</span>
          <input v-model="collectForm.station" placeholder="如 PLAN-0001" />
        </label>
        <label class="filter-item">
          <span>开始小时</span>
          <input v-model.number="collectForm.startHour" type="number" min="0" max="23" />
        </label>
        <label class="filter-item">
          <span>结束小时</span>
          <input v-model.number="collectForm.endHour" type="number" min="0" max="23" />
        </label>
        <button class="btn primary" type="submit">送入队列</button>
      </form>

      <table class="data-table queue-table">
        <thead>
          <tr>
            <th v-for="column in queueColumns" :key="column">{{ column }}</th>
            <th>核对操作（值班员）</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in queueRows" :key="String(row.id)" :class="rowClass(row)">
            <td>{{ row['电站编号'] }}</td>
            <td>{{ row['日期'] }}</td>
            <td>{{ String(row['小时']).padStart(2, '0') }}:00</td>
            <td>
              <span v-if="row['零值确认']" class="zero-cell">0（人工零值）</span>
              <span v-else-if="row['发电量'] === null || row['发电量'] === ''" class="blank-cell">— 未采集</span>
              <span v-else>{{ row['发电量'] }}</span>
            </td>
            <td><span :class="{ 'blank-cell': row['辐照度'] === null || row['辐照度'] === '' }">{{ formatValue(row['辐照度']) }}</span></td>
            <td><span :class="{ 'missing-cell': row['组件温度'] === null || row['组件温度'] === '' }">{{ formatValue(row['组件温度']) }}</span></td>
            <td><span :class="{ 'missing-cell': row['环境温度'] === null || row['环境温度'] === '' }">{{ formatValue(row['环境温度']) }}</span></td>
            <td>{{ row['来源'] }}</td>
            <td>
              <span class="badge" :class="badgeClass(row)">{{ row['队列状态'] }}</span>
              <span v-if="row['零值确认'] && row['队列状态'] !== '人工零值' && row['队列状态'] !== '已入库'" class="badge zero">零值已确认</span>
              <span v-if="row['队列状态'] === '已入库'" class="record-no">{{ row['记录编号'] }}</span>
            </td>
            <td class="row-actions cell-stack">
              <template v-if="editingId === row.id">
                <input v-model="editForm['组件温度']" placeholder="组件温度" class="mini-input" />
                <input v-model="editForm['环境温度']" placeholder="环境温度" class="mini-input" />
                <input v-model="editForm['发电量']" placeholder="发电量（可留空）" class="mini-input" />
                <input v-model="editForm['辐照度']" placeholder="辐照度（可留空）" class="mini-input" />
                <button class="link" type="button" @click="saveSupplement(row)">保存补录</button>
                <button class="link cancel" type="button" @click="editingId = null">取消</button>
              </template>
              <template v-else-if="row['队列状态'] !== '已入库'">
                <button
                  v-if="row['队列状态'] === '待补录' || row['队列状态'] === '未采集'"
                  class="link"
                  type="button"
                  @click="startSupplement(row)"
                >逐条补录</button>
                <button
                  v-if="canConfirmZero(row)"
                  class="link zero-link"
                  type="button"
                  @click="confirmZero(row)"
                >确认人工零值</button>
                <span v-if="row['队列状态'] === '待入库'" class="muted-hint">待写入</span>
              </template>
              <span v-else class="muted-hint">已入正式记录</span>
            </td>
          </tr>
          <tr v-if="!queueRows.length">
            <td :colspan="queueColumns.length + 1" class="empty-state">该筛选范围内没有队列行；指定日期后空范围仍会保留电站×小时模板</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>共 {{ queueTotal }} 行队列记录（空范围模板保留、未采集不删除）</span>
        <span v-if="message" :class="messageOk ? '' : 'error-text'">{{ message }}</span>
      </footer>
    </template>

    <!-- ============ 正式发电记录 ============ -->
    <template v-else>
      <div class="stat-row">
        <article class="stat-card">
          <span class="stat-label">正式记录总数</span>
          <strong class="stat-value">{{ total }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">另存表格范围</span>
          <strong class="stat-value file-name">发电记录_{{ exportFilters.date || '全部' }}.csv</strong>
        </article>
      </div>

      <form class="filter-bar" @submit.prevent="loadFormal">
        <label class="filter-item">
          <span>记录编号</span>
          <input v-model="formalFilters.keyword" placeholder="按记录编号检索" />
        </label>
        <label class="filter-item">
          <span>数据状态</span>
          <select v-model="formalFilters.status">
            <option value="">全部</option>
            <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
          </select>
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetFormalFilters">重置条件</button>
      </form>

      <form class="filter-bar" @submit.prevent="exportFormal">
        <label class="filter-item">
          <span>另存-电站编号（留空=全部）</span>
          <input v-model="exportFilters.station" placeholder="如 PLAN-0001" />
        </label>
        <label class="filter-item">
          <span>另存-日期（留空=全部）</span>
          <input v-model="exportFilters.date" placeholder="YYYY-MM-DD" />
        </label>
        <button class="btn primary" type="submit">另存为表格文件（CSV）</button>
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
            <td :colspan="columns.length + 1" class="empty-state">暂无正式发电记录；请先在采集核对队列完成校验入库</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>共 {{ total }} 条正式发电记录（仅包含校验通过的行）</span>
        <span v-if="message" :class="messageOk ? '' : 'error-text'">{{ message }}</span>
      </footer>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | boolean | null>

const session = useSessionStore()
const ENDPOINT = '/api/power_data'
const tab = ref<'queue' | 'formal'>('queue')

// ---- 正式记录 ----
const columns = ['记录编号', '电站编号', '发电量', '辐照度', '组件温度', '环境温度', '记录时间', '数据状态']
const actions = ['标记偏低', '确认异常', '数据补录']
const statuses = ['正常', '偏低', '异常', '补录']
const rows = ref<Row[]>([])
const total = ref(0)
const formalFilters = ref<Record<string, string>>({ keyword: '', status: '' })
const exportFilters = ref<Record<string, string>>({ station: '', date: '' })

// ---- 采集核对队列 ----
const queueColumns = ['电站编号', '日期', '小时', '发电量', '辐照度', '组件温度', '环境温度', '来源', '队列状态']
const queueStatuses = ['未采集', '待补录', '人工零值', '待入库', '已入库']
const queueRows = ref<Row[]>([])
const queueTotal = ref(0)
const queueFilters = ref<Record<string, string>>({ date: '', station: '', status: '' })
const showCollectForm = ref(false)
const collectForm = reactive({ date: '', station: '', startHour: 6, endHour: 18 })
const editingId = ref<number | null>(null)
const editForm = reactive<Record<string, string | number>>({ 组件温度: '', 环境温度: '', 发电量: '', 辐照度: '' })

const message = ref('')
const messageOk = ref(true)

function notify(text: string, ok = true) {
  message.value = text
  messageOk.value = ok
}

const queueStats = computed(() => {
  const count = (status: string) => queueRows.value.filter((row) => row['队列状态'] === status).length
  return [
    { label: '校验区滞留（缺温度）', value: count('待补录'), tone: 'tone-warn' },
    { label: '待写入正式记录', value: count('待入库'), tone: 'tone-ready' },
    { label: '人工零值（已确认）', value: queueRows.value.filter((row) => row['零值确认'] === true).length, tone: 'tone-zero' },
    { label: '未采集空白（模板保留）', value: count('未采集'), tone: 'tone-blank' },
    { label: '已入正式记录', value: count('已入库'), tone: 'tone-done' },
  ]
})

function switchTab(next: 'queue' | 'formal') {
  tab.value = next
  message.value = ''
  if (next === 'queue') {
    void loadQueue()
  } else {
    void loadFormal()
  }
}

function resetQueueFilters() {
  queueFilters.value = { date: '', station: '', status: '' }
  void loadQueue()
}

function resetFormalFilters() {
  formalFilters.value = { keyword: '', status: '' }
  void loadFormal()
}

function isBlank(value: Row[keyof Row]) {
  return value === null || value === '' || value === undefined
}

function formatValue(value: Row[keyof Row]) {
  return isBlank(value) ? '—' : String(value)
}

function canConfirmZero(row: Row) {
  if (row['队列状态'] === '已入库' || row['队列状态'] === '待入库' || row['队列状态'] === '人工零值') {
    return false
  }
  const power = row['发电量']
  return isBlank(power) || Number(power) === 0
}

function rowClass(row: Row) {
  return {
    'row-validating': row['队列状态'] === '待补录',
    'row-blank': row['队列状态'] === '未采集',
    'row-zero': row['零值确认'] === true,
  }
}

function badgeClass(row: Row) {
  const map: Record<string, string> = {
    未采集: 'blank',
    待补录: 'warn',
    人工零值: 'zero',
    待入库: 'ready',
    已入库: 'done',
  }
  return map[String(row['队列状态'])] ?? ''
}

async function postAction(path: string, body: Record<string, unknown>, reload: () => Promise<void>) {
  try {
    const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
    const payload = await response.json()
    notify(payload.message ?? (response.ok ? '操作已完成' : '操作未生效'), response.ok && payload.ok !== false)
    if (response.ok && payload.ok !== false) {
      await reload()
    }
  } catch (error) {
    notify(error instanceof Error ? error.message : '接口请求失败', false)
  }
}

async function loadQueue() {
  const params = new URLSearchParams()
  Object.entries(queueFilters.value).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  params.set('size', '1000')
  try {
    const response = await request(`${ENDPOINT}/queue?${params.toString()}`)
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload.detail ?? '采集核对队列读取失败')
    }
    queueRows.value = (payload.items ?? []) as Row[]
    queueTotal.value = payload.total ?? queueRows.value.length
  } catch (error) {
    notify(error instanceof Error ? error.message : '采集核对队列读取失败', false)
  }
}

async function runCollect() {
  const values: Record<string, unknown> = {
    日期: collectForm.date,
    开始小时: collectForm.startHour,
    结束小时: collectForm.endHour,
  }
  if (collectForm.station.trim()) {
    values['电站列表'] = [collectForm.station.trim()]
  }
  await postAction(`${ENDPOINT}/queue/collect`, { values }, loadQueue)
  showCollectForm.value = false
}

function startSupplement(row: Row) {
  editingId.value = Number(row.id)
  editForm['组件温度'] = isBlank(row['组件温度']) ? '' : String(row['组件温度'])
  editForm['环境温度'] = isBlank(row['环境温度']) ? '' : String(row['环境温度'])
  editForm['发电量'] = isBlank(row['发电量']) ? '' : String(row['发电量'])
  editForm['辐照度'] = isBlank(row['辐照度']) ? '' : String(row['辐照度'])
}

async function saveSupplement(row: Row) {
  const values: Record<string, unknown> = { 操作人: session.operator }
  ;(['组件温度', '环境温度', '发电量', '辐照度'] as const).forEach((field) => {
    const text = String(editForm[field] ?? '').trim()
    if (text !== '') values[field] = text
  })
  await postAction(`${ENDPOINT}/queue/${row.id}/supplement`, { values }, loadQueue)
  editingId.value = null
}

async function confirmZero(row: Row) {
  await postAction(`${ENDPOINT}/queue/${row.id}/confirm_zero`, { values: { 操作人: session.operator } }, loadQueue)
}

async function commitQueue() {
  await postAction(`${ENDPOINT}/queue/commit`, { values: { ...queueFilters.value } }, loadQueue)
}

function exportFormal() {
  const params = new URLSearchParams()
  if (exportFilters.value.station) params.set('station', exportFilters.value.station)
  if (exportFilters.value.date) params.set('date', exportFilters.value.date)
  const suffix = params.toString()
  window.open(`${ENDPOINT}/queue/export${suffix ? `?${suffix}` : ''}`, '_blank')
  notify('已生成表格文件，浏览器开始下载（仅包含校验通过的正式记录）')
}

async function loadFormal() {
  const params = new URLSearchParams()
  if (formalFilters.value.keyword) params.set('keyword', formalFilters.value.keyword)
  if (formalFilters.value.status) params.set('status', formalFilters.value.status)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error('正式发电记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = (payload.items ?? []) as Row[]
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    notify(error instanceof Error ? error.message : '正式发电记录列表读取失败', false)
  }
}

async function runAction(action: string, row: Row) {
  await postAction(`${ENDPOINT}/${row.id}/actions`, { values: { action } }, loadFormal)
}

onMounted(() => {
  collectForm.date = '2026-09-27'
  queueFilters.value.date = '2026-09-27'
  void loadQueue()
})
</script>

<style scoped>
.cell-stack {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
  align-items: center;
  min-width: 220px;
}
.mini-input {
  width: 118px;
  padding: 3px 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
  font-size: 12px;
}
.link.cancel {
  color: var(--muted);
}
.zero-link {
  color: #b54708;
}
.badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  margin-right: 4px;
  white-space: nowrap;
}
.badge.blank { background: #eef2f6; color: var(--muted); border: 1px dashed #c2ccd8; }
.badge.warn { background: #fef3c7; color: #92400e; }
.badge.zero { background: #ffedd5; color: #9a3412; }
.badge.ready { background: #dcfce7; color: #166534; }
.badge.done { background: #e0e7ff; color: #3730a3; }
.blank-cell { color: #94a3b8; }
.missing-cell { color: #b42318; font-weight: 600; }
.zero-cell { color: #9a3412; font-weight: 600; }
.muted-hint { color: var(--muted); font-size: 12px; }
.record-no { font-size: 12px; color: #3730a3; }
.row-validating { background: #fffdf5; }
.row-blank { background: #fafbfc; color: var(--muted); }
.row-zero { background: #fff9f5; }
.tone-warn .stat-value { color: #b45309; }
.tone-ready .stat-value { color: #15803d; }
.tone-zero .stat-value { color: #c2410c; }
.tone-blank .stat-value { color: var(--muted); }
.tone-done .stat-value { color: #4338ca; }
.file-name { font-size: 14px; }
.collect-panel {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: flex-end;
  background: #fff;
  border: 1px dashed var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
}
.queue-table select,
.queue-table .mini-input {
  font-family: inherit;
}
</style>
