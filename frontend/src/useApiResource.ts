import { useEffect, useState } from 'react'
import { apiRequest } from './api'

type StoredResource<T> = { generation: string; data: T | null; loading: boolean; error: string | null }

export function useApiResource<T>(path: string | null, refreshKey = 0, pollIntervalMs = 0) {
  const [stored, setStored] = useState<StoredResource<T>>({ generation: '', data: null, loading: Boolean(path), error: null })
  const [attempt, setAttempt] = useState(0)
  const generation = path ? `${path}|${refreshKey}|${attempt}` : ''

  useEffect(() => {
    if (!path) return
    let stopped = false
    let inFlight = false
    let controller: AbortController | null = null

    const load = () => {
      if (stopped || inFlight) return
      inFlight = true
      controller = new AbortController()
      const activeController = controller
      apiRequest<T>(path, { signal: activeController.signal })
        .then(value => {
          if (!stopped) setStored({ generation, data: value, loading: false, error: null })
        })
        .catch(reason => {
          if (!stopped && !activeController.signal.aborted) {
            setStored(previous => ({
              generation,
              data: previous.generation === generation ? previous.data : null,
              loading: false,
              error: reason instanceof Error ? reason.message : 'Unable to load API data.',
            }))
          }
        })
        .finally(() => { inFlight = false })
    }

    load()
    const timer = pollIntervalMs > 0 ? window.setInterval(load, pollIntervalMs) : undefined
    return () => {
      stopped = true
      if (timer !== undefined) window.clearInterval(timer)
      controller?.abort()
    }
  }, [path, refreshKey, attempt, pollIntervalMs, generation])

  const current = stored.generation === generation
    ? stored
    : { generation, data: null, loading: Boolean(path), error: null }
  return {
    data: path ? current.data : null,
    loading: path ? current.loading : false,
    error: current.error,
    retry: () => setAttempt(value => value + 1),
  }
}
