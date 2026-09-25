<script>
  import Observation from './Observation.svelte'

  let username = 'processor'
  let password = 'herb123456'
  let token = localStorage.getItem('herb_token') || ''
  let role = localStorage.getItem('herb_role') || ''
  let rows = []
  let herb = '白芍'
  let tempC = 110
  let minutes = 10
  let error = ''
  let route = location.hash

  window.addEventListener('hashchange', () => (route = location.hash))

  async function api(path, options = {}) {
    const res = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || '请求失败')
    return data
  }

  async function enter() {
    const data = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    token = data.access_token
    role = data.role
    localStorage.setItem('herb_token', token)
    localStorage.setItem('herb_role', role)
    await load()
  }

  async function load() {
    rows = await api('/api/batches')
  }

  async function save() {
    error = ''
    try {
      await api('/api/batches', {
        method: 'POST',
        body: JSON.stringify({
          herb,
          steps: [{ name: '清炒', temp_c: Number(tempC), minutes: Number(minutes) }],
        }),
      })
      // 出锅即入冷却观察簿，写入成功后自动进入观察页
      location.hash = '#/observation'
    } catch (err) {
      error = err.message
    }
  }

  function leave() {
    localStorage.clear()
    token = ''
    role = ''
  }

  if (token) load()
</script>

<main>
  {#if !token}
    <h1>饮片炮制记录台</h1>
    <p>炮制记录整包保存。清炒温度须在 80 到 150，时长须在 5 到 30 分钟。</p>
    <input bind:value={username} />
    <input type="password" bind:value={password} />
    <button on:click={enter}>登录</button>
    <p>processor / herb123456 可写；checker / check123456 只读</p>
  {:else}
    <header class="topbar">
      <span class="brand">饮片炮制记录台</span>
      <nav>
        <a href="#/" class:current={route !== '#/observation'}>炮制记录</a>
        <a href="#/observation" class:current={route === '#/observation'}>冷却观察</a>
      </nav>
      <span class="user">{role === 'writer' ? '炮制员' : '质检员'} ·
        <button on:click={leave}>退出</button>
      </span>
    </header>

    {#if route === '#/observation'}
      <Observation {api} {role} />
    {:else}
      <section>
        {#if role === 'writer'}
          <div class="formline">
            <input bind:value={herb} placeholder="饮片" />
            <input type="number" bind:value={tempC} title="清炒温度℃" />
            <input type="number" bind:value={minutes} title="清炒时长分钟" />
            <button on:click={save}>写入清炒记录</button>
          </div>
          {#if error}<p class="error">{error}</p>{/if}
        {/if}
        <ul>
          {#each rows as row}
            <li>{row.herb} · {row.verdict} · {row.reason} · 温度 {row.doc.steps[0].temp_c}</li>
          {/each}
        </ul>
      </section>
    {/if}
  {/if}
</main>

<style>
  main { font-family: sans-serif; max-width: 720px; margin: 24px auto; color: #3f2f1f; }
  .topbar {
    display: flex; align-items: center; gap: 16px;
    border-bottom: 2px solid #7c2d12; padding-bottom: 8px; margin-bottom: 16px;
  }
  .brand { color: #7c2d12; font-weight: bold; font-size: 18px; }
  nav { flex: 1; display: flex; gap: 12px; }
  nav a { color: #7c2d12; text-decoration: none; padding: 4px 8px; border-radius: 4px; }
  nav a.current { background: #7c2d12; color: #fff; }
  .user { color: #6b5d4f; font-size: 13px; }
  .formline { margin-bottom: 8px; }
  input { margin-right: 8px; padding: 6px; }
  .error { color: #b91c1c; }
</style>
