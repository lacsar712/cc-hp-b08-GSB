<script>
  let { api, role } = $props()

  let minutesInput = $state(30)
  let observing = $state([])
  let completed = $state([])
  let error = $state('')
  let notice = $state('')
  let now = $state(new Date())
  let loaded = $state(false)

  const timer = setInterval(() => (now = new Date()), 1000)

  $effect(() => {
    return () => clearInterval(timer)
  })

  async function load() {
    const data = await api('/api/observation')
    minutesInput = data.minutes
    observing = data.observing
    completed = data.completed
    loaded = true
  }

  async function saveMinutes() {
    error = ''
    notice = ''
    try {
      const value = Number(minutesInput)
      if (!Number.isFinite(value) || value < 0) {
        error = '观察分钟须为不小于 0 的数'
        return
      }
      const data = await api('/api/observation/minutes', {
        method: 'PUT',
        body: JSON.stringify({ minutes: value }),
      })
      minutesInput = data.minutes
      notice = `观察分钟已设为 ${data.minutes} 分钟`
      await load()
    } catch (err) {
      error = err.message
    }
  }

  async function finish(row) {
    error = ''
    notice = ''
    // 前端先拦一道：未满观察分钟禁止完成
    if (new Date() < new Date(row.due_at)) {
      error = `未满观察分钟（${fmtRemaining(row)}），禁止完成观察`
      return
    }
    try {
      await api(`/api/observation/${row.id}/complete`, { method: 'POST' })
      await load()
    } catch (err) {
      error = err.message
      await load()
    }
  }

  function fmtClock(iso) {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  }

  function fmtRemaining(row) {
    const ms = new Date(row.due_at) - now
    if (ms <= 0) return '已满时'
    const total = Math.ceil(ms / 1000)
    const m = Math.floor(total / 60)
    const s = total % 60
    return `剩 ${m} 分 ${String(s).padStart(2, '0')} 秒`
  }

  load().catch((err) => (error = err.message))
</script>

<section class="observation">
  <h2>出锅冷却观察簿</h2>

  <div class="settings">
    <strong>观察分钟设置</strong>
    {#if role === 'writer'}
      <input type="number" min="0" step="0.1" bind:value={minutesInput} />
      <button on:click={saveMinutes}>保存观察分钟</button>
    {:else}
      <span class="readonly">当前 {minutesInput} 分钟（质检员仅可查看，不可修改）</span>
    {/if}
  </div>

  {#if error}<p class="error">{error}</p>{/if}
  {#if notice}<p class="notice">{notice}</p>{/if}

  <h3>观察中</h3>
  {#if !loaded}
    <p>加载中…</p>
  {:else if observing.length === 0}
    <p class="empty">暂无观察中的批次。</p>
  {:else}
    <table>
      <thead>
        <tr><th>批次</th><th>饮片</th><th>出锅时刻</th><th>观察时长</th><th>状态</th><th></th></tr>
      </thead>
      <tbody>
        {#each observing as row (row.id)}
          <tr>
            <td>#{row.id}</td>
            <td>{row.herb}</td>
            <td>{fmtClock(row.created_at)}</td>
            <td>{row.observe_minutes} 分钟</td>
            <td class:due={now >= new Date(row.due_at)}>{fmtRemaining(row)}</td>
            <td>
              {#if role === 'writer'}
                <button disabled={now < new Date(row.due_at)} on:click={() => finish(row)}>
                  完成观察
                </button>
              {:else}
                <span class="readonly">—</span>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  <h3>已完成</h3>
  {#if completed.length === 0}
    <p class="empty">暂无已完成观察的批次。</p>
  {:else}
    <table>
      <thead>
        <tr><th>批次</th><th>饮片</th><th>出锅时刻</th><th>完成时刻</th><th>记录人</th></tr>
      </thead>
      <tbody>
        {#each completed as row (row.id)}
          <tr>
            <td>#{row.id}</td>
            <td>{row.herb}</td>
            <td>{fmtClock(row.created_at)}</td>
            <td>{fmtClock(row.observe_completed_at)}</td>
            <td>{row.created_by}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>

<style>
  .observation h2 { color: #7c2d12; }
  .settings {
    background: #fdf6ec; border: 1px solid #e7d8c4; border-radius: 6px;
    padding: 10px 12px; margin-bottom: 12px; display: flex; align-items: center; gap: 10px;
  }
  .settings input { width: 90px; padding: 6px; }
  .readonly { color: #6b5d4f; }
  .error { color: #b91c1c; }
  .notice { color: #166534; }
  .empty { color: #8a7a68; }
  table { border-collapse: collapse; width: 100%; margin-bottom: 20px; }
  th, td { border: 1px solid #d8c9b6; padding: 6px 10px; text-align: left; font-size: 14px; }
  th { background: #f4ece1; }
  .due { color: #166534; font-weight: bold; }
  button:disabled { color: #a8a29e; cursor: not-allowed; }
</style>
