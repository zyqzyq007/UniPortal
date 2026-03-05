const KEY = 'uni-portal-front-logs'

type FrontLog = {
  time: string
  level: 'error' | 'info'
  message: string
  code?: number
  detail?: string
}

const readLogs = (): FrontLog[] => {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as FrontLog[]) : []
  } catch {
    return []
  }
}

export const pushFrontLog = (entry: Omit<FrontLog, 'time'>) => {
  const next = [{ ...entry, time: new Date().toISOString() }, ...readLogs()].slice(0, 200)
  localStorage.setItem(KEY, JSON.stringify(next))
}

