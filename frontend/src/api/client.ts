import axios from 'axios'

const baseURL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') || 'http://127.0.0.1:8000'

export const api = axios.create({
  baseURL,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.response.use(
  (r) => r,
  (err) => {
    const message =
      err.response?.data?.detail ?? err.message ?? 'Request failed'
    return Promise.reject(
      typeof message === 'string' ? new Error(message) : new Error(JSON.stringify(message)),
    )
  },
)
