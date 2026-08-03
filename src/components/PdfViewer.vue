<template>
  <div class="pdf-viewer">
    <div v-if="loading" class="pdf-loading">
      <div class="mini-spinner"></div>
      <p>{{ loadingMsg }}</p>
    </div>
    <div v-else-if="error" class="pdf-error">
      <p>{{ error }}</p>
    </div>
    <div v-else class="pdf-pages">
      <canvas v-for="p in numPages" :key="p" :ref="el => setCanvasRef(p, el)"></canvas>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, nextTick } from 'vue'

// PDF.js v3.11.174 — UMD build (works in all browsers, no ESM issues)
const PDFJS_VER = '3.11.174'
const PDFJS_URL = `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${PDFJS_VER}`

const props = defineProps<{ data: ArrayBuffer }>()

const loading = ref(true)
const loadingMsg = ref('正在加载 PDF...')
const error = ref('')
const numPages = ref(0)
const canvasRefs = new Map<number, HTMLCanvasElement | null>()

function setCanvasRef(page: number, el: any) {
  if (el) canvasRefs.set(page, el)
}

// Load PDF.js UMD script (not ESM module — broader browser support)
function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = src
    s.onload = () => resolve()
    s.onerror = () => reject(new Error(`Failed to load ${src}`))
    document.head.appendChild(s)
  })
}

async function ensurePdfJs(): Promise<any> {
  const w = window as any
  if (w.pdfjsLib) {
    if (!w.pdfjsLib.GlobalWorkerOptions.workerSrc) {
      w.pdfjsLib.GlobalWorkerOptions.workerSrc = `${PDFJS_URL}/pdf.worker.min.js`
    }
    return w.pdfjsLib
  }
  loadingMsg.value = '正在加载 PDF.js 渲染引擎...'
  await loadScript(`${PDFJS_URL}/pdf.min.js`)
  if (!w.pdfjsLib) throw new Error('PDF.js 加载后未找到 pdfjsLib')
  w.pdfjsLib.GlobalWorkerOptions.workerSrc = `${PDFJS_URL}/pdf.worker.min.js`
  return w.pdfjsLib
}

async function loadPdf() {
  loading.value = true
  error.value = ''
  numPages.value = 0
  canvasRefs.clear()
  try {
    const lib = await ensurePdfJs()

    loadingMsg.value = '正在解析 PDF...'
    // Copy buffer because PDF.js detaches (transfers) the original
    const buf = props.data.slice(0)
    const loadingTask = lib.getDocument({ data: new Uint8Array(buf) })
    const pdf = await loadingTask.promise
    numPages.value = pdf.numPages

    loadingMsg.value = `正在渲染 ${pdf.numPages} 页...`
    await nextTick()

    for (let i = 1; i <= pdf.numPages; i++) {
      const page = await pdf.getPage(i)
      const canvas = canvasRefs.get(i)
      if (!canvas) continue

      const containerWidth = canvas.parentElement?.clientWidth || 600
      // Fit to container width
      const baseViewport = page.getViewport({ scale: 1 })
      const scale = Math.min(containerWidth / baseViewport.width, 2)
      const viewport = page.getViewport({ scale })

      const context = canvas.getContext('2d')
      if (!context) continue
      canvas.width = viewport.width
      canvas.height = viewport.height
      canvas.style.width = '100%'
      canvas.style.height = 'auto'

      await page.render({ canvasContext: context, viewport }).promise
    }
  } catch (e: any) {
    error.value = `PDF 渲染失败: ${e?.message || '未知错误'}`
    console.error('PDF render error:', e)
  } finally {
    loading.value = false
  }
}

onMounted(loadPdf)
watch(() => props.data, loadPdf)
</script>

<style scoped>
.pdf-viewer { width: 100%; }

.pdf-loading {
  text-align: center;
  padding: 40px;
  color: #64748b;
}

.pdf-loading .mini-spinner {
  width: 24px;
  height: 24px;
  border: 3px solid #e2e8f0;
  border-top-color: #1e40af;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 8px;
}

@keyframes spin { to { transform: rotate(360deg); } }

.pdf-error {
  text-align: center;
  padding: 32px;
  color: #dc2626;
  font-size: 14px;
}

.pdf-pages {
  max-height: 60vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  background: #525659;
  padding: 12px;
  border-radius: 4px;
}

.pdf-pages canvas {
  max-width: 100%;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
  background: white;
}
</style>
