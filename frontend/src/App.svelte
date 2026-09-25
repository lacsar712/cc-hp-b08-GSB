<script>
  import { onMount, onDestroy } from 'svelte'
  import CoolingBook from './CoolingBook.svelte'
  import { api, currentRole } from './lib/api.js'

  let username = 'processor'
  let password = 'herb123456'
  let token = localStorage.getItem('herb_token') || ''
  let role = localStorage.getItem('herb_role') || ''
  let rows = []
  let herb = '白芍'
  let tempC = 110
  let minutes = 10
  let error = ''
  let notice = ''
  let route = location.hash || '#/records'

  function onHash() {
    route = location.hash || '#/records'
  }
  onMount(() => {
    window.addEventListener('hashchange', onHash)
    if (token) load()
  })
  onDestroy(() => window.removeEventListener('hashchange', onHash))

  async function enter() {
    error = ''
    try {
      const data = await api('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      })
      token = data.access_token
      role = data.role
      localStorage.setItem('herb_token', token)
      localStorage.setItem('herb_role', role)
      route = '#/records'
      location.hash = '#/records'
      await load()
    } catch (err) {
      error = err.message
    }
  }

  async function load() {
    rows = await api('/api/batches')
  }

  async function save() {
    error = ''
    notice = ''
    try {
      const created = await api('/api/batches', {
        method: 'POST',
        body: JSON.stringify({
          herb,
          steps: [{ name: '清炒', temp_c: Number(tempC), minutes: Number(minutes) }],
        }),
      })
      await load()
      // 写入成功后自动进入冷却观察簿
      notice = `${created.herb} 已出锅入簿，请到冷却观察簿观察`
      location.hash = '#/cooling'
    } catch (err) {
      error = err.message
    }
  }

  function leave() {
    localStorage.clear()
    token = ''
    role = ''
    location.hash = '#/records'
  }
</script>

<main>
  <h1>饮片炮制记录台</h1>
  {#if !token}
    <p>炮制记录整包保存。清炒温度须在 80 到 150，时长须在 5 到 30 分钟。出锅后自动进入冷却观察簿。</p>
    <input bind:value={username} />
    <input type="password" bind:value={password} />
    <button on:click={enter}>登录</button>
    {#if error}<p class="error">{error}</p>{/if}
    <p>processor / herb123456 可写；checker / check123456 只读</p>
  {:else}
    <nav class="topbar">
      <a class:active={route === '#/records'} href="#/records">炮制记录</a>
      <a class:active={route === '#/cooling'} href="#/cooling">冷却观察</a>
      <span class="spacer"></span>
      <span class="who">{role === 'writer' ? '炮制员' : '质检员'} · </span>
      <button on:click={leave}>退出</button>
    </nav>

    {#if route === '#/cooling'}
      <CoolingBook />
    {:else}
      <section>
        {#if role === 'writer'}
          <div class="write-card">
            <input bind:value={herb} placeholder="饮片" />
            <input type="number" bind:value={tempC} title="清炒温度℃" placeholder="温度℃" />
            <input type="number" bind:value={minutes} title="清炒时长分钟" placeholder="时长(分)" />
            <button on:click={save}>写入清炒记录</button>
            <p class="hint">写入成功后自动进入冷却观察簿。</p>
          </div>
          {#if error}<p class="error">{error}</p>{/if}
          {#if notice}<p class="ok">{notice}</p>{/if}
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
  main {
    font-family: sans-serif;
    max-width: 880px;
    margin: 24px auto;
    color: #3f2f1f;
  }
  h1 {
    color: #7c2d12;
  }
  .topbar {
    display: flex;
    align-items: center;
    gap: 16px;
    border-bottom: 2px solid #e7d8c8;
    padding: 8px 4px;
    margin-bottom: 16px;
  }
  .topbar a {
    text-decoration: none;
    color: #7a5a3a;
    padding: 4px 10px;
    border-radius: 6px;
  }
  .topbar a.active {
    background: #7c2d12;
    color: #fff;
    font-weight: bold;
  }
  .topbar .spacer {
    flex: 1;
  }
  .topbar .who {
    color: #7a6450;
    font-size: 14px;
  }
  .write-card {
    margin: 12px 0;
  }
  input {
    margin-right: 8px;
    padding: 6px;
  }
  .hint {
    color: #7a6450;
    font-size: 13px;
  }
  .error {
    color: #b91c1c;
  }
  .ok {
    color: #15803d;
  }
</style>
