import React, { createContext, useContext, useReducer, useRef, useCallback, useEffect } from 'react'
import { API_BASE } from '../config'

const PipelineContext = createContext(null)

function reducer(state, action) {
  switch (action.type) {
    case 'ADD_JOB':
      return { ...state, jobs: [...state.jobs, action.job] }
    case 'UPDATE_JOB':
      return {
        ...state,
        jobs: state.jobs.map(j => j.id === action.id ? { ...j, ...action.updates } : j),
      }
    case 'APPEND_LOG':
      return {
        ...state,
        jobs: state.jobs.map(j =>
          j.id === action.id ? { ...j, logs: [...j.logs, action.message] } : j
        ),
      }
    case 'MERGE_RESULTS':
      return {
        ...state,
        jobs: state.jobs.map(j =>
          j.id === action.id ? { ...j, results: { ...(j.results || {}), ...action.data } } : j
        ),
      }
    case 'PATCH_JOB_RESULTS':
      return {
        ...state,
        jobs: state.jobs.map(j =>
          j.id === action.id ? { ...j, results: action.updater(j.results) } : j
        ),
      }
    case 'CANCEL_JOB':
      return {
        ...state,
        jobs: state.jobs.map(j =>
          j.id === action.id && j.status === 'queued' ? { ...j, status: 'cancelled' } : j
        ),
      }
    case 'SET_ACTIVE':
      return { ...state, activeJobId: action.id }
    default:
      return state
  }
}

export function PipelineProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, { jobs: [], activeJobId: null })
  const controllersRef = useRef(new Map()) // jobId -> AbortController
  const runningRef = useRef(new Set())     // guard against double-start

  const runJob = useCallback(async (id, thesis, settings) => {
    if (runningRef.current.has(id)) return
    runningRef.current.add(id)

    const controller = new AbortController()
    controllersRef.current.set(id, controller)
    dispatch({ type: 'UPDATE_JOB', id, updates: { status: 'running' } })

    try {
      const response = await fetch(`${API_BASE}/api/research`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thesis, settings }),
        signal: controller.signal,
      })

      if (!response.ok) {
        const text = await response.text()
        throw new Error(text || `HTTP ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let gotResult = false

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          let event
          try { event = JSON.parse(line.slice(6)) } catch { continue }

          if (event.type === 'log') {
            dispatch({ type: 'APPEND_LOG', id, message: event.message })
          } else if (event.type === 'phase_result') {
            dispatch({ type: 'MERGE_RESULTS', id, data: event.data })
          } else if (event.type === 'result') {
            gotResult = true
            dispatch({
              type: 'UPDATE_JOB', id,
              updates: { results: event.data, status: 'done', completedAt: new Date().toISOString() },
            })
          } else if (event.type === 'error') {
            dispatch({
              type: 'UPDATE_JOB', id,
              updates: { error: event.message, status: 'error', completedAt: new Date().toISOString() },
            })
          }
        }
      }

      if (!gotResult) {
        dispatch({
          type: 'UPDATE_JOB', id,
          updates: { status: 'done', completedAt: new Date().toISOString() },
        })
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        dispatch({ type: 'APPEND_LOG', id, message: '— stopped by user —' })
        dispatch({
          type: 'UPDATE_JOB', id,
          updates: { status: 'stopped', completedAt: new Date().toISOString() },
        })
      } else {
        dispatch({
          type: 'UPDATE_JOB', id,
          updates: { error: err.message, status: 'error', completedAt: new Date().toISOString() },
        })
      }
    } finally {
      controllersRef.current.delete(id)
      runningRef.current.delete(id)
    }
  }, [])

  // Auto-advance the queue: when nothing is running, start the next queued job
  useEffect(() => {
    const isRunning = state.jobs.some(j => j.status === 'running')
    if (!isRunning) {
      const next = state.jobs.find(j => j.status === 'queued')
      if (next) runJob(next.id, next.thesis, next.settings)
    }
  }, [state.jobs, runJob])

  const addJob = useCallback((thesis, settings) => {
    const id = crypto.randomUUID()
    dispatch({
      type: 'ADD_JOB',
      job: {
        id, thesis, settings,
        status: 'queued',
        logs: [], results: null, error: null,
        startedAt: new Date().toISOString(), completedAt: null,
      },
    })
    dispatch({ type: 'SET_ACTIVE', id })
    return id
  }, [])

  const cancelJob = useCallback((id) => {
    const controller = controllersRef.current.get(id)
    if (controller) controller.abort()
    dispatch({ type: 'CANCEL_JOB', id })
  }, [])

  const selectJob = useCallback((id) => {
    dispatch({ type: 'SET_ACTIVE', id })
  }, [])

  const patchJobResults = useCallback((id, updater) => {
    dispatch({ type: 'PATCH_JOB_RESULTS', id, updater })
  }, [])

  const value = {
    jobs: state.jobs,
    activeJobId: state.activeJobId,
    activeJob: state.jobs.find(j => j.id === state.activeJobId) ?? null,
    addJob,
    cancelJob,
    selectJob,
    patchJobResults,
  }

  return <PipelineContext.Provider value={value}>{children}</PipelineContext.Provider>
}

export function usePipeline() {
  const ctx = useContext(PipelineContext)
  if (!ctx) throw new Error('usePipeline must be used within PipelineProvider')
  return ctx
}
