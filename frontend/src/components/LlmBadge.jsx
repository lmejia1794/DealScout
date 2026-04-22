import React from 'react'

const BACKEND_COLOR = {
  google:     'bg-green-500',
  groq:       'bg-orange-500',
  openrouter: 'bg-purple-500',
}

const BACKEND_LABEL = {
  google:     'Google AI',
  groq:       'Groq',
  openrouter: 'OpenRouter',
}

function shortModel(model = '', backend = '') {
  if (!model) return BACKEND_LABEL[backend] || backend
  return model
    .replace('gemini-2.5-flash-lite', 'Gemini 2.5 Flash Lite')
    .replace('gemini-2.5-flash', 'Gemini 2.5 Flash')
    .replace('gemini-2.0-flash', 'Gemini 2.0 Flash')
    .replace('meta-llama/llama-3.3-70b-instruct:free', 'Llama 3.3 70B')
    .replace('llama-3.3-70b-versatile', 'Llama 3.3 70B')
    .replace('deepseek/deepseek-r1:free', 'DeepSeek R1')
    .replace('nvidia/nemotron-3-super-120b-a12b:free', 'Nemotron 120B')
}

export default function LlmBadge({ meta }) {
  if (!meta?.backend) return null

  const dot   = BACKEND_COLOR[meta.backend] || 'bg-gray-400'
  const label = BACKEND_LABEL[meta.backend] || meta.backend
  const model = shortModel(meta.model, meta.backend)
  const tooltip = `${label} · ${meta.model || ''}${meta.search ? ' · web search' : ''}`

  return (
    <span
      title={tooltip}
      className="inline-flex items-center gap-1.5 text-[10px] font-medium text-gray-400 bg-gray-50 border border-gray-200 px-2 py-0.5 rounded-full cursor-default select-none"
    >
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dot}`} />
      {model}
      {meta.search && <span className="text-blue-400 font-normal">·search</span>}
    </span>
  )
}
