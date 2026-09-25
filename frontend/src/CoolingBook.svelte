<script>
  import { onMount, onDestroy } from 'svelte'
  import { api, currentRole } from './lib/api.js'

  let role = currentRole()
  let settingMinutes = 30
  let settingDraft = 30
  let settingMsg = ''
  let settingError = ''
  let observations = []
  let observingRows = []
  let loadError = ''
  let rowErrors = {}
  // 每行的分钟草稿按 id 存，倒计时每秒重算时不会打断正在输入的值
  let drafts = {}
  let tick = 0

  let timer = null
  let refetchTimer = null

  const isObserving = (o) => !o.completed_at
  const doneRows = () => observations.filter((o) => o.completed_at)

  function remainingOf(o) {
    return Math.max(0, Math.ceil((new Date(o.due_at).getTime() - Date.now()) / 1000))
  }

  // 倒计时随本机秒针刷新
  $: {
    void tick
    observingRows = observations.filter(isObserving).map((o) => ({
      ...o,
      remaining: remainingOf(o),
      canComplete: remainingOf(o) <= 0,
    }))
  }

  function fmtRemain(sec) {
    const h = Math.floor(sec / 3600)
    const m = Math.floor((sec % 3600) / 60)
    const s = sec % 60
    const mm = String(m).padStart(2, '0')
    const ss = String(s).padStart(2, '0')
    return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
  }

  function fmtTime(iso) {
    if (!iso) return '—'
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  }

  async function loadSetting() {
    const s = await api('/api/observation-setting')
    settingMinutes = s.observe_minutes
    settingDraft = s.observe_minutes
  }

  async function loadObservations() {
    const rows = await api('/api/observations')
    // 给新出现的观察行播种分钟草稿；已存在的草稿保留
    for (const o of rows) {
      if (!o.completed_at && drafts[o.id] === undefined) drafts[o.id] = o.observe_minutes
    }
    observations = rows
  }

  async function saveSetting() {
    settingMsg = ''
    settingError = ''
    try {
      const v = Number(settingDraft)
      if (!Number.isFinite(v) || v < 0) throw new Error('观察分钟须为不小于 0 的数')
      const s = await api('/api/observation-setting', {
        method: 'PUT',
        body: JSON.stringify({ minutes: v }),
      })
      settingMinutes = s.observe_minutes
      settingDraft = s.observe_minutes
      settingMsg = `已保存：新出锅的记录将按 ${s.observe_minutes} 分钟观察`
    } catch (err) {
      settingError = err.message
    }
  }

  async function changeMinutes(o) {
    try {
      const v = Number(drafts[o.id])
      if (!Number.isFinite(v) || v < 0) throw new Error('观察分钟须为不小于 0 的数')
      await api(`/api/observations/${o.id}/minutes`, {
        method: 'PATCH',
        body: JSON.stringify({ minutes: v }),
      })
      rowErrors = { ...rowErrors, [o.id]: '' }
      await loadObservations()
    } catch (err) {
      rowErrors = { ...rowErrors, [o.id]: err.message }
    }
  }

  async function complete(o) {
    try {
      await api(`/api/observations/${o.id}/complete`, { method: 'POST' })
      rowErrors = { ...rowErrors, [o.id]: '' }
      await loadObservations()
    } catch (err) {
      // 未满观察分钟：服务端拒绝（400），就地提示
      rowErrors = { ...rowErrors, [o.id]: err.message }
    }
  }

  onMount(async () => {
    try {
      await Promise.all([loadSetting(), loadObservations()])
    } catch (err) {
      loadError = err.message
    }
    timer = setInterval(() => (tick += 1), 1000)
    refetchTimer = setInterval(loadObservations, 10000)
  })

  onDestroy(() => {
    clearInterval(timer)
    clearInterval(refetchTimer)
  })
</script>

<section class="cooling-book">
  <h2>出锅冷却观察簿</h2>
  {#if loadError}
    <p class="error">观察簿加载失败：{loadError}</p>
  {/if}

  {#if role === 'writer'}
    <div class="panel setting">
      <h3>观察分钟设置</h3>
      <p class="hint">对新出锅写入的记录生效；当前默认观察 <strong>{settingMinutes}</strong> 分钟。</p>
      <label>
        观察分钟
        <input type="number" min="0" step="0.5" bind:value={settingDraft} />
      </label>
      <button on:click={saveSetting}>保存观察分钟</button>
      {#if settingMsg}<p class="ok">{settingMsg}</p>{/if}
      {#if settingError}<p class="error">{settingError}</p>{/if}
    </div>
  {:else}
    <p class="hint">质检员只读：可查看观察簿，不能完成观察、不能改分钟。</p>
  {/if}

  <div class="panel">
    <h3>观察中（{observingRows.length}）</h3>
    {#if observingRows.length === 0}
      <p class="empty">当前没有观察中的批次。</p>
    {:else}
      <table>
        <thead>
          <tr>
            <th>饮片</th>
            <th>结论</th>
            <th>出锅时刻</th>
            <th>观察分钟</th>
            <th>剩余冷却</th>
            {#if role === 'writer'}<th>改分钟</th>{/if}
            <th>完成观察</th>
          </tr>
        </thead>
        <tbody>
          {#each observingRows as o (o.id)}
            <tr class:due={o.canComplete}>
              <td>{o.herb}</td>
              <td>{o.verdict}</td>
              <td>{fmtTime(o.started_at)}</td>
              <td>{o.observe_minutes}</td>
              <td class="countdown">{o.canComplete ? '已满时' : fmtRemain(o.remaining)}</td>
              {#if role === 'writer'}
                <td>
                  <input type="number" min="0" step="0.5" bind:value={drafts[o.id]} />
                  <button on:click={() => changeMinutes(o)}>改分钟</button>
                </td>
                <td>
                  <button class:primary={o.canComplete} on:click={() => complete(o)}>完成观察</button>
                </td>
              {:else}
                <td class="readonly">—</td>
              {/if}
            </tr>
            {#if role === 'writer' && rowErrors[o.id]}
              <tr class="msg-row"><td colspan="7"><p class="error">{rowErrors[o.id]}</p></td></tr>
            {/if}
          {/each}
        </tbody>
      </table>
    {/if}
  </div>

  <div class="panel">
    <h3>已完成（{doneRows().length}）</h3>
    {#if doneRows().length === 0}
      <p class="empty">还没有完成观察的批次。</p>
    {:else}
      <table>
        <thead>
          <tr>
            <th>饮片</th>
            <th>结论</th>
            <th>出锅时刻</th>
            <th>观察分钟</th>
            <th>完成时刻</th>
          </tr>
        </thead>
        <tbody>
          {#each doneRows() as o (o.id)}
            <tr>
              <td>{o.herb}</td>
              <td>{o.verdict}</td>
              <td>{fmtTime(o.started_at)}</td>
              <td>{o.observe_minutes}</td>
              <td>{fmtTime(o.completed_at)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
</section>

<style>
  .cooling-book h2 {
    color: #7c2d12;
  }
  .panel {
    border: 1px solid #e7d8c8;
    border-radius: 8px;
    padding: 12px 16px;
    margin: 16px 0;
    background: #fffaf3;
  }
  .panel h3 {
    margin: 4px 0 10px;
    color: #5b3a22;
  }
  .hint {
    color: #7a6450;
  }
  table {
    border-collapse: collapse;
    width: 100%;
  }
  th,
  td {
    border-bottom: 1px solid #ecdfcf;
    padding: 8px 10px;
    text-align: left;
    font-size: 14px;
  }
  tr.due {
    background: #f1f8ec;
  }
  .countdown {
    font-variant-numeric: tabular-nums;
    font-weight: bold;
    color: #b45309;
  }
  tr.due .countdown {
    color: #15803d;
  }
  input[type='number'] {
    width: 80px;
    padding: 4px 6px;
  }
  button {
    margin-left: 6px;
    padding: 4px 10px;
    cursor: pointer;
  }
  button.primary {
    background: #15803d;
    color: #fff;
    border-color: #15803d;
  }
  .error {
    color: #b91c1c;
    margin: 6px 0;
  }
  .ok {
    color: #15803d;
    margin: 6px 0;
  }
  .empty {
    color: #9a8671;
  }
  .readonly {
    color: #9a8671;
  }
  .msg-row td {
    border-bottom: none;
    padding-top: 0;
  }
</style>
