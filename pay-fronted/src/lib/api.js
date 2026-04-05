// API 基础配置
const LOCAL_API_BASE = 'http://127.0.0.1:8000/v1'
const PROD_API_BASE = 'https://dash.xca.sh/v1'

const resolveApiBaseUrl = () => {
  const envBase = import.meta.env?.VITE_API_BASE_URL
  if (envBase) {
    return envBase.replace(/\/$/, '')
  }

  if (typeof window !== 'undefined') {
    const hostname = window.location.hostname
    if (hostname === '127.0.0.1' || hostname === 'localhost') {
      return LOCAL_API_BASE
    }
  }

  return PROD_API_BASE
}

const API_BASE_URL = resolveApiBaseUrl()

const handleResponse = async (response, defaultMessage) => {
  if (response.ok) {
    return response.json()
  }

  let message = `${defaultMessage}: HTTP ${response.status}`
  try {
    const data = await response.json()
    if (data?.message) {
      message = data.message
    }
  } catch {
    // ignore json parse error, fall back to default message
  }

  throw new Error(message)
}

// 获取账单详情
export const getInvoice = async (sysNo) => {
  try {
    const response = await fetch(`${API_BASE_URL}/invoice/${sysNo}`, {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    })
    return await handleResponse(response, '获取账单信息失败')
  } catch (error) {
    console.error('获取账单详情失败:', error)
    throw error
  }
}

// 设置支付方式
export const selectPayMethod = async (sysNo, crypto, chain) => {
  try {
    const response = await fetch(`${API_BASE_URL}/invoice/${sysNo}/select-method`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify({
        crypto,
        chain,
      }),
    })
    return await handleResponse(response, '设置支付方式失败')
  } catch (error) {
    console.error('选择代币和公链失败:', error)
    throw error
  }
}

// 获取 URL 参数
export const getUrlParam = (name) => {
  if (typeof window === 'undefined') return null

  const urlParams = new URLSearchParams(window.location.search)
  const queryValue = urlParams.get(name)
  if (queryValue) {
    return queryValue
  }

  if (name === 'sys_no') {
    // 使用 VITE_PAY_MOUNT 作为页面挂载路径，与资源 base URL（/static/pay/）解耦
    const mount = (import.meta?.env?.VITE_PAY_MOUNT ?? '/pay').replace(/^\/|\/$/g, '')
    const mountSegments = mount ? mount.split('/').filter(Boolean) : []

    const pathSegments = window.location.pathname
      .split('/')
      .filter(Boolean)
      .slice(mountSegments.length)

    if (pathSegments.length > 0) {
      return decodeURIComponent(pathSegments[pathSegments.length - 1])
    }

    const hash = window.location.hash.replace(/^#\/?/, '')
    if (hash) {
      const hashSegments = hash.split('/').filter(Boolean)
      if (hashSegments.length > 0) {
        return decodeURIComponent(hashSegments[hashSegments.length - 1])
      }
    }
  }

  return null
}
