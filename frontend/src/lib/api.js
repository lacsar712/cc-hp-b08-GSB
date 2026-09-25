export async function api(path, options = {}) {
  const token = localStorage.getItem('herb_token') || ''
  const res = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || '请求失败')
  return data
}

export function currentRole() {
  return localStorage.getItem('herb_role') || ''
}
