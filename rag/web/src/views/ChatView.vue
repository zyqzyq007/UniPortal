<template>
  <div class="chat-view">
    <!-- Main Chat Container -->
    <div class="chat-container">
      <!-- Chat Header -->
      <div class="chat-header">
        <div class="header-left">
          <h2>智能问答</h2>
        </div>
        <div class="header-actions">
          <div class="mode-toggle">
            <button
              :class="['mode-btn', { active: chatStore.mode === 'thinking' }]"
              @click="chatStore.mode = 'thinking'"
              title="深度思考模式：完整意图分析 + 文档评估 + 诊断回答"
              data-testid="mode-thinking"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2a8 8 0 0 1 8 8c0 3.4-2.1 6.3-5 7.5V20h-6v-2.5C6.1 16.3 4 13.4 4 10a8 8 0 0 1 8-8z"/>
                <path d="M10 22h4"/>
              </svg>
              <span>深度</span>
            </button>
            <button
              :class="['mode-btn', { active: chatStore.mode === 'fast' }]"
              @click="chatStore.mode = 'fast'"
              title="快速模式：直接检索 + 生成回答"
              data-testid="mode-fast"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
              </svg>
              <span>快速</span>
            </button>
          </div>
          <button class="btn-icon" @click="toggleStreamMode" :title="useStream ? '流式输出已开启' : '流式输出已关闭'" data-testid="stream-toggle">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
            </svg>
            <span class="stream-indicator" :class="{ active: useStream }"></span>
          </button>
          <button class="btn-new-session" @click="handleNewSession" title="新建会话" data-testid="new-session">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 5v14M5 12h14"/>
            </svg>
            <span>新对话</span>
          </button>
        </div>
      </div>

      <!-- Messages Area -->
      <div class="messages-area" ref="messagesRef">
        <!-- Welcome Message -->
        <div v-if="chatStore.messages.length === 0" class="welcome-message" data-testid="welcome">
          <div class="welcome-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M12 2L2 7L12 12L22 7L12 2Z"/>
              <path d="M2 17L12 22L22 17"/>
              <path d="M2 12L12 17L22 12"/>
            </svg>
          </div>
          <h3>欢迎使用智能知识问答系统</h3>
          <p>基于已上传知识库的智能检索与问答，支持多种文档格式。</p>
          <div class="quick-actions">
            <button class="quick-btn" @click="askQuestion('如何上传文档到知识库？')" data-testid="quick-q-1">上传文档</button>
            <button class="quick-btn" @click="askQuestion('支持哪些文档格式？')" data-testid="quick-q-2">文档格式</button>
            <button class="quick-btn" @click="askQuestion('你能帮我做什么？')" data-testid="quick-q-3">系统介绍</button>
          </div>
        </div>

        <!-- Message List -->
        <div
          v-for="(msg, index) in chatStore.messages"
          :key="index"
          :class="['message', msg.role]"
          data-testid="message"
        >
          <div class="message-avatar">
            <div class="avatar-icon" :class="msg.role">
              <svg v-if="msg.role === 'user'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                <circle cx="12" cy="7" r="4"/>
              </svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2L2 7L12 12L22 7L12 2Z"/>
                <path d="M2 17L12 22L22 17"/>
                <path d="M2 12L12 17L22 12"/>
              </svg>
            </div>
          </div>
          <div class="message-body">
            <div class="message-header">
              <span class="message-role">{{ msg.role === 'user' ? '用户' : 'AI助手' }}</span>
              <span class="message-time" v-if="msg.timestamp">{{ formatTime(msg.timestamp) }}</span>
            </div>
            <!-- Hide empty content bubble during streaming, show status instead -->
            <template v-if="msg.isStreaming && !msg.content">
              <div class="stream-status">
                <div class="status-dot"></div>
                <span>{{ getStatusText() }}</span>
              </div>
            </template>
            <template v-else-if="msg.content">
              <div class="message-content markdown-content" v-html="renderMarkdown(msg.content)"></div>
            </template>
            <div
              v-if="msg.role === 'assistant' && !msg.isStreaming && shouldShowModeCard(msg)"
              class="mode-card"
            >
              <p v-if="getIntentLabel(msg.intent)"><strong>对话类型：</strong>{{ getIntentLabel(msg.intent) }}</p>
              <p v-if="getProfileLabel(msg.metadata?.prompt_profile)"><strong>回答模式：</strong>{{ getProfileLabel(msg.metadata?.prompt_profile) }}</p>
              <p v-if="msg.metadata?.force_rag" class="mode-note">
                检测到专业问题，已自动切换到知识库检索模式。
              </p>
              <button
                v-if="msg.sources && msg.sources.length > 0"
                class="source-toggle-btn"
                @click="openSources(msg.sources)"
                data-testid="sources-toggle"
              >
                查看依据来源 ({{ msg.sources.length }})
              </button>
            </div>
            <div
              v-if="msg.role === 'assistant' && !msg.isStreaming && hasStructuredAnswer(msg)"
              class="structured-answer-card"
            >
              <h4>结构化回答</h4>
              <p v-if="msg.structuredAnswer?.summary"><strong>{{ sectionLabel(msg, 0) }}：</strong>{{ msg.structuredAnswer?.summary }}</p>
              <p v-if="msg.structuredAnswer?.notes"><strong>{{ sectionLabel(msg, 3) }}：</strong>{{ msg.structuredAnswer?.notes }}</p>
              <p v-if="msg.structuredAnswer?.gaps"><strong>{{ sectionLabel(msg, 5) }}：</strong>{{ msg.structuredAnswer?.gaps }}</p>
            </div>
            <div class="message-footer" v-if="msg.role === 'assistant' && !msg.isStreaming && msg.processingTime">
              <span class="processing-time">{{ msg.processingTime.toFixed(0) }}ms</span>
            </div>
            <!-- Feedback row: thumbs up / down / correction. trace_id + message_id
                 ride in metadata and drive the eval flywheel on negative feedback. -->
            <div
              v-if="msg.role === 'assistant' && !msg.isStreaming"
              class="feedback-row"
              data-testid="feedback-row"
            >
              <template v-if="msg.feedbackSubmitted">
                <span class="feedback-done" data-testid="feedback-done">已反馈</span>
              </template>
              <template v-else>
                <button
                  class="feedback-btn"
                  title="有帮助"
                  data-testid="feedback-up"
                  @click="submitFeedback(msg, 'THUMBS_UP')"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
                  </svg>
                </button>
                <button
                  class="feedback-btn"
                  title="无帮助"
                  data-testid="feedback-down"
                  @click="submitFeedback(msg, 'THUMBS_DOWN')"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zM17 2h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/>
                  </svg>
                </button>
                <button
                  class="feedback-btn feedback-correct-btn"
                  title="提交纠正"
                  data-testid="feedback-correct-open"
                  @click="openCorrection(msg)"
                >
                  纠错
                </button>
              </template>
            </div>
            <!-- Inline correction input -->
            <div
              v-if="msg.role === 'assistant' && !msg.isStreaming && correctingMessage === msg"
              class="correction-box"
              data-testid="correction-box"
            >
              <textarea
                v-model="correctionText"
                class="correction-input"
                placeholder="请输入正确的回答内容..."
                rows="3"
                data-testid="correction-input"
              ></textarea>
              <div class="correction-actions">
                <button class="correction-submit" data-testid="correction-submit" @click="submitCorrection(msg)">提交</button>
                <button class="correction-cancel" data-testid="correction-cancel" @click="cancelCorrection">取消</button>
              </div>
            </div>
          </div>
        </div>

        <!-- Typing Indicator (only for non-stream loading) -->
        <div v-if="chatStore.isLoading && !chatStore.isStreaming" class="message assistant typing">
          <div class="message-avatar">
            <div class="avatar-icon assistant">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2L2 7L12 12L22 7L12 2Z"/>
                <path d="M2 17L12 22L22 17"/>
                <path d="M2 12L12 17L22 12"/>
              </svg>
            </div>
          </div>
          <div class="message-body">
            <div class="typing-indicator">
              <span></span><span></span><span></span>
            </div>
          </div>
        </div>
      </div>

      <!-- Input Area -->
      <div class="input-area">
        <div class="input-wrapper">
          <textarea
            v-model="inputText"
            @keydown.enter.exact.prevent="handleSend"
            :placeholder="uploadStore.isUploading ? '文档上传中，请稍候...' : '输入您的问题，按 Enter 发送...'"
            rows="1"
            ref="textareaRef"
            :disabled="chatStore.isLoading || chatStore.isStreaming || uploadStore.isUploading"
            maxlength="2000"
            data-testid="chat-input"
          ></textarea>
          <div class="input-actions">
            <div class="left-actions">
              <span class="char-count">{{ inputText.length }} / 2000</span>
            </div>
            <div class="right-actions">
              <button
                class="btn-send"
                @click="handleSend"
                :disabled="!inputText.trim() || chatStore.isLoading || chatStore.isStreaming || uploadStore.isUploading"
                data-testid="chat-send"
              >
                <span>发送</span>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Sources Panel -->
    <transition name="slide">
      <div v-if="showSources && sources.length > 0" class="sources-panel" data-testid="sources-panel">
        <div class="sources-header">
          <h3>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
            </svg>
            参考来源
          </h3>
          <button class="btn-close" @click="showSources = false">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
          </button>
        </div>
        <div class="source-list">
          <div v-for="(source, i) in sources" :key="i" class="source-item" data-testid="source-item">
            <div class="source-header">
              <span class="source-number">{{ i + 1 }}</span>
              <span class="source-title">{{ source.title || '知识库文档' }}</span>
            </div>
            <div class="source-content">{{ truncateText(source.content, 150) }}</div>
            <div class="source-meta" v-if="source.score != null" data-testid="source-score">
              <span class="relevance-score">相关度: {{ formatSourceScore(source.score) }}</span>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, watch, onMounted } from 'vue'
import { useChatStore, type SourceDocument, type ChatMessage } from '@/stores/chat'
import { useUploadStore } from '@/stores/upload'
import { useToast } from '@/stores/toast'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const chatStore = useChatStore()
const uploadStore = useUploadStore()
const toast = useToast()

const inputText = ref('')
const messagesRef = ref<HTMLElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const showSources = ref(false)
const sources = ref<SourceDocument[]>([])
const useStream = ref(true)
// Feedback UI state: which message has its correction box open + draft text.
const correctingMessage = ref<ChatMessage | null>(null)
const correctionText = ref('')

// Markdown render cache
const mdCache = new Map<string, string>()

// Configure marked
marked.setOptions({
  breaks: true,
  gfm: true,
})

onMounted(() => {
  autoResizeTextarea()
})

function renderMarkdown(text: string): string {
  if (!text) return ''
  const cached = mdCache.get(text)
  if (cached) return cached
  try {
    const rawHtml = marked.parse(text) as string
    const result = DOMPurify.sanitize(rawHtml, {
      ALLOWED_TAGS: [
        'p', 'br', 'strong', 'em', 'u', 's', 'code', 'pre',
        'ul', 'ol', 'li', 'a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'blockquote', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'hr'
      ],
      ALLOWED_ATTR: ['href', 'target', 'rel']
    })
    mdCache.set(text, result)
    // Prevent memory leak: limit cache size
    if (mdCache.size > 200) {
      const firstKey = mdCache.keys().next().value
      if (firstKey) mdCache.delete(firstKey)
    }
    return result
  } catch {
    console.error('Markdown sanitization failed; rendering escaped plain text')
    return escapeHtml(text)
  }
}

function escapeHtml(text: string): string {
  const entities: Record<string, string> = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }
  return text.replace(/[&<>"']/g, (character) => entities[character])
}

function formatTime(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatSourceScore(score: number): string {
  if (Number.isFinite(score) && score >= 0 && score <= 1) {
    return `${(score * 100).toFixed(1)}%`
  }
  return Number.isFinite(score) ? score.toFixed(4) : '不可用'
}

function truncateText(text: string, maxLength: number): string {
  if (!text) return ''
  return text.length > maxLength ? text.substring(0, maxLength) + '...' : text
}

function getStatusText(): string {
  const node = chatStore.currentNode
  const intent = chatStore.currentIntent

  if (node === 'agent') return '正在分析问题...'
  if (node === 'retrieve') return '正在检索知识库...'
  if (node === 'rewrite') return '正在优化查询...'
  if (node === 'generate') return '正在生成回答...'
  if (node === 'fast_generate') return '快速生成回答中...'
  if (intent === 'general_chat') return '正在思考...'
  return '处理中...'
}

function autoResizeTextarea() {
  if (textareaRef.value) {
    textareaRef.value.style.height = 'auto'
    textareaRef.value.style.height = Math.min(textareaRef.value.scrollHeight, 150) + 'px'
  }
}

watch(inputText, () => {
  autoResizeTextarea()
})

async function handleSend() {
  const text = inputText.value.trim()
  if (!text || chatStore.isLoading || chatStore.isStreaming || uploadStore.isUploading) return

  inputText.value = ''
  autoResizeTextarea()
  sources.value = []
  showSources.value = false

  try {
    if (useStream.value) {
      await chatStore.sendMessageStream(text)
      syncSourcesFromLatestAssistant()
    } else {
      const response = await chatStore.sendMessage(text)
      if (response?.sources?.length) {
        sources.value = response.sources
        showSources.value = true
      }
    }
  } catch (e) {
    console.error('Send failed:', e)
  }

  await nextTick()
  scrollToBottom()
}

function askQuestion(question: string) {
  inputText.value = question
  handleSend()
}

function hasStructuredAnswer(msg: ChatMessage): boolean {
  return Boolean(
    msg.structuredAnswer &&
    (
      msg.structuredAnswer.summary ||
      msg.structuredAnswer.details?.length ||
      msg.structuredAnswer.steps?.length ||
      msg.structuredAnswer.notes ||
      msg.structuredAnswer.sources?.length ||
      msg.structuredAnswer.gaps
    )
  )
}

/**
 * Caption for a positional StructuredAnswer slot, sourced from the active
 * domain profile's section_template (carried in metadata.section_labels).
 * Keeps the UI domain-neutral: an aviation profile renders its own captions
 * (e.g. "风险与安全提示" for slot 3) without this view hardcoding any domain
 * text. Falls back to a neutral generic label when no profile label is present
 * (e.g. older cached messages). [domain-generalization F-C1]
 */
function sectionLabel(msg: ChatMessage, index: number): string {
  const labels = msg.metadata?.section_labels as string[] | undefined
  if (labels && Array.isArray(labels) && index < labels.length) {
    return labels[index]
  }
  const neutral = ['摘要', '补充说明', '信息缺口']
  const map = [0, 3, 5]
  const pos = map.indexOf(index)
  return pos >= 0 ? neutral[pos] : ''
}

function getIntentLabel(intent?: string): string {
  if (!intent) return ''
  if (intent === 'general_chat') return '普通咨询'
  if (intent === 'rag_query') return '知识库问答'
  if (intent === 'degraded') return '降级服务'
  return ''
}

function getProfileLabel(profile?: string): string {
  if (!profile) return ''
  // Domain-neutral labels derived from the profile label embedded in the tag.
  // Works for any domain (general_v1, <domain>_<suffix>_v1, etc.) without
  // hardcoding any domain-specific strings.
  if (profile.endsWith('_identity_v1')) return '身份介绍'
  if (profile.endsWith('_general_v1')) return '通用咨询'
  if (profile.endsWith('_fast_v1')) return '快速检索模式'
  // Generate-style tags carry the domain-specific suffix (e.g. a profile may
  // set a structured-output suffix; general uses the plain _v1) — surface a
  // domain-neutral label.
  return '知识库问答'
}

function shouldShowModeCard(msg: ChatMessage): boolean {
  return Boolean(
    getIntentLabel(msg.intent) ||
    getProfileLabel(msg.metadata?.prompt_profile) ||
    msg.metadata?.force_rag ||
    (msg.sources && msg.sources.length > 0)
  )
}

function openSources(list: SourceDocument[]) {
  sources.value = list
  showSources.value = true
}

function syncSourcesFromLatestAssistant() {
  const reversed = [...chatStore.messages].reverse()
  const lastAssistant = reversed.find((m) => m.role === 'assistant')
  if (lastAssistant?.sources?.length) {
    sources.value = lastAssistant.sources
    showSources.value = true
  }
}

function handleNewSession() {
  chatStore.newSession()
  sources.value = []
  showSources.value = false
}

function toggleStreamMode() {
  useStream.value = !useStream.value
}

function scrollToBottom() {
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}

// --- Feedback handlers -------------------------------------------------
// Submit a simple thumbs up/down/flag. trace_id/message_id ride in the message
// metadata (set by the backend) and drive the eval flywheel on negative types.
async function submitFeedback(msg: ChatMessage, type: 'THUMBS_UP' | 'THUMBS_DOWN' | 'FLAG') {
  if (msg.feedbackSubmitted) return
  const ok = await chatStore.submitFeedback(msg, type)
  if (ok) {
    toast.show('反馈已提交', 'success')
  } else {
    toast.show('反馈提交失败，请重试', 'error')
  }
}

function openCorrection(msg: ChatMessage) {
  if (msg.feedbackSubmitted) return
  correctingMessage.value = msg
  correctionText.value = ''
}

function cancelCorrection() {
  correctingMessage.value = null
  correctionText.value = ''
}

async function submitCorrection(msg: ChatMessage) {
  const trimmed = correctionText.value.trim()
  if (!trimmed) {
    toast.show('请填写纠正内容', 'error')
    return
  }
  const ok = await chatStore.submitFeedback(msg, 'CORRECTION', trimmed)
  if (ok) {
    cancelCorrection()
    toast.show('纠错已提交', 'success')
  } else {
    toast.show('纠错提交失败，请重试', 'error')
  }
}

// Auto scroll when messages change or content streams
watch(
  () => ({
    len: chatStore.messages.length,
    lastContent: chatStore.messages[chatStore.messages.length - 1]?.content,
  }),
  () => {
    nextTick(scrollToBottom)
  }
)
</script>

<style scoped>
.chat-view {
  display: flex;
  height: 100%;
  gap: 0;
}

/* Chat Container */
.chat-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--neutral-50);
  overflow: hidden;
}

/* Chat Header */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-md) var(--spacing-lg);
  border-bottom: 1px solid var(--neutral-200);
  background: var(--neutral-50);
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
}

.chat-header h2 {
  font-size: 18px;
  font-weight: 600;
  margin: 0;
}

.header-actions {
  display: flex;
  gap: var(--spacing-sm);
  align-items: center;
}

/* Mode Toggle */
.mode-toggle {
  display: flex;
  border: 1px solid var(--neutral-200);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--neutral-100);
}

.mode-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: none;
  background: transparent;
  color: var(--neutral-500);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.mode-btn svg {
  width: 14px;
  height: 14px;
}

.mode-btn:hover {
  color: var(--neutral-700);
  background: var(--neutral-200);
}

.mode-btn.active {
  background: linear-gradient(135deg, var(--primary-500), var(--primary-600));
  color: white;
}

.mode-btn.active:hover {
  background: linear-gradient(135deg, var(--primary-600), var(--primary-700));
}

.btn-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--neutral-600);
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  transition: all var(--transition-fast);
}

.btn-icon:hover {
  background: var(--neutral-100);
  color: var(--neutral-900);
}

.btn-icon svg {
  width: 20px;
  height: 20px;
}

.stream-indicator {
  position: absolute;
  bottom: 4px;
  right: 4px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--neutral-400);
  transition: background var(--transition-fast);
}

.stream-indicator.active {
  background: var(--success-500);
  box-shadow: 0 0 6px var(--success-500);
}

.btn-new-session {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 12px;
  border-radius: var(--radius-md);
  background: var(--neutral-100);
  color: var(--neutral-600);
  font-size: 12px;
  font-weight: 500;
  border: 1px solid var(--neutral-200);
  transition: all var(--transition-fast);
}

.btn-new-session:hover {
  background: var(--primary-50);
  border-color: var(--primary-300);
  color: var(--primary-600);
}

.btn-new-session svg {
  width: 16px;
  height: 16px;
}

/* Messages Area */
.messages-area {
  flex: 1;
  overflow-y: auto;
  padding: var(--spacing-lg);
}

/* Welcome Message */
.welcome-message {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
  padding: var(--spacing-2xl);
}

.welcome-icon {
  width: 72px;
  height: 72px;
  background: linear-gradient(135deg, var(--primary-100), var(--primary-200));
  border-radius: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--spacing-lg);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.15);
}

.welcome-icon svg {
  width: 36px;
  height: 36px;
  color: var(--primary-500);
}

.welcome-message h3 {
  font-size: 22px;
  font-weight: 700;
  margin-bottom: 8px;
  color: var(--neutral-800);
}

.welcome-message p {
  color: var(--neutral-500);
  margin-bottom: var(--spacing-xl);
  font-size: 14px;
}

.quick-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
}

.quick-btn {
  padding: 8px 16px;
  background: var(--neutral-50);
  border: 1px solid var(--neutral-200);
  border-radius: 999px;
  color: var(--neutral-700);
  font-size: 13px;
  transition: all var(--transition-fast);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}

.quick-btn:hover {
  background: var(--primary-50);
  border-color: var(--primary-200);
  color: var(--primary-600);
  box-shadow: 0 2px 6px rgba(99, 102, 241, 0.12);
}

/* Message */
.message {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.message.user {
  flex-direction: row-reverse;
}

.message-avatar {
  flex-shrink: 0;
  margin-top: 2px;
}

.avatar-icon {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-lg);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.avatar-icon.user {
  background: linear-gradient(135deg, var(--primary-400), var(--primary-600));
  color: white;
}

.avatar-icon.assistant {
  background: linear-gradient(135deg, var(--primary-100), var(--primary-200));
  color: var(--primary-500);
}

.avatar-icon svg {
  width: 16px;
  height: 16px;
}

.message-body {
  max-width: 75%;
  min-width: 0;
}

.message.user .message-body {
  align-items: flex-end;
}

.message-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  margin-bottom: 4px;
}

.message.user .message-header {
  flex-direction: row-reverse;
}

.message-role {
  font-size: 12px;
  font-weight: 600;
  color: var(--neutral-500);
  letter-spacing: 0.02em;
}

.message-time {
  font-size: 11px;
  color: var(--neutral-400);
}

.message-content {
  padding: 10px 14px;
  border-radius: 12px;
  background: var(--neutral-100);
  color: var(--neutral-800);
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}

.message.user .message-content {
  background: linear-gradient(135deg, var(--primary-500), var(--primary-600));
  color: white;
  border-bottom-right-radius: 4px;
  box-shadow: 0 1px 4px rgba(59, 130, 246, 0.2);
}

.message.assistant .message-content {
  border-bottom-left-radius: 4px;
  border: 1px solid var(--neutral-200);
}

.message-footer {
  margin-top: var(--spacing-xs);
  text-align: right;
}

.mode-card {
  margin-top: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid var(--neutral-200);
  background: var(--neutral-100);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.mode-card p {
  margin: 0;
  font-size: 11px;
  color: var(--neutral-500);
}

.mode-card strong {
  color: var(--neutral-700);
}

.mode-note {
  color: #92400e !important;
}

.source-toggle-btn {
  font-size: 11px;
  line-height: 1;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--neutral-50);
  color: var(--primary-600);
  border: 1px solid var(--primary-200);
  transition: all var(--transition-fast);
}

.source-toggle-btn:hover {
  background: var(--primary-50);
  border-color: var(--primary-300);
}

/* Feedback row (thumbs up/down/correction) */
.feedback-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}

.feedback-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  line-height: 1;
  padding: 4px 8px;
  border-radius: 999px;
  background: var(--neutral-50);
  color: var(--neutral-500);
  border: 1px solid var(--neutral-200);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.feedback-btn svg {
  width: 14px;
  height: 14px;
}

.feedback-btn:hover {
  background: var(--primary-50);
  color: var(--primary-600);
  border-color: var(--primary-300);
}

.feedback-correct-btn {
  padding: 4px 10px;
}

.feedback-done {
  font-size: 11px;
  color: var(--success-500);
  font-weight: 500;
}

.correction-box {
  margin-top: 8px;
  padding: 10px;
  border-radius: 8px;
  border: 1px solid var(--primary-200);
  background: var(--primary-50);
}

.correction-input {
  width: 100%;
  font-size: 13px;
  padding: 8px;
  border-radius: 6px;
  border: 1px solid var(--neutral-200);
  resize: vertical;
  font-family: inherit;
  box-sizing: border-box;
}

.correction-input:focus {
  outline: none;
  border-color: var(--primary-400);
}

.correction-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
  justify-content: flex-end;
}

.correction-submit {
  font-size: 12px;
  padding: 4px 14px;
  border-radius: 6px;
  background: var(--primary-500);
  color: white;
  border: none;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.correction-submit:hover {
  background: var(--primary-600);
}

.correction-cancel {
  font-size: 12px;
  padding: 4px 14px;
  border-radius: 6px;
  background: var(--neutral-100);
  color: var(--neutral-600);
  border: none;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.correction-cancel:hover {
  background: var(--neutral-200);
}

.structured-answer-card {
  margin-top: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--primary-200);
  background: var(--primary-50);
}

.structured-answer-card h4 {
  margin: 0 0 6px;
  font-size: 12px;
  color: var(--primary-500);
  font-weight: 600;
}

.structured-answer-card p {
  margin: 4px 0;
  font-size: 12px;
  color: var(--neutral-700);
  line-height: 1.5;
}

.processing-time {
  font-size: 11px;
  color: var(--neutral-400);
}

/* Typing Indicator */
.typing-indicator {
  display: flex;
  gap: 5px;
  padding: 10px 14px;
}

.typing-indicator span {
  width: 7px;
  height: 7px;
  background: var(--primary-400);
  border-radius: 50%;
  animation: bounce 1.4s infinite ease-in-out;
}

.typing-indicator span:nth-child(1) { animation-delay: 0s; }
.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 80%, 100% {
    transform: scale(0.8);
    opacity: 0.4;
  }
  40% {
    transform: scale(1.1);
    opacity: 1;
  }
}

.stream-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  background: var(--primary-50);
  border-radius: 10px;
  font-size: 13px;
  color: var(--primary-500);
  border: 1px solid var(--primary-200);
}

.status-dot {
  width: 7px;
  height: 7px;
  background: var(--primary-500);
  border-radius: 50%;
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

/* Input Area */
.input-area {
  padding: 12px 20px 20px;
  border-top: 1px solid var(--neutral-200);
  background: var(--neutral-50);
}

.input-wrapper {
  background: var(--neutral-50);
  border: 1px solid var(--neutral-200);
  border-radius: 16px;
  overflow: hidden;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.input-wrapper:focus-within {
  border-color: var(--primary-400);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

textarea {
  width: 100%;
  padding: 12px 16px 4px;
  border: none;
  background: transparent;
  resize: none;
  font-size: 14px;
  line-height: 1.6;
  outline: none;
  min-height: 24px;
  max-height: 150px;
  color: var(--neutral-800);
}

.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 12px 10px;
}

.char-count {
  font-size: 11px;
  color: var(--neutral-400);
}

.btn-send {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: linear-gradient(135deg, var(--primary-500), var(--primary-600));
  color: white;
  border-radius: 10px;
  font-weight: 500;
  font-size: 13px;
  transition: all var(--transition-fast);
  box-shadow: 0 1px 3px rgba(59, 130, 246, 0.2);
}

.btn-send:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 3px 8px rgba(59, 130, 246, 0.3);
}

.btn-send:active:not(:disabled) {
  transform: translateY(0);
}

.btn-send:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-send svg {
  width: 15px;
  height: 15px;
}

/* Sources Panel */
.sources-panel {
  width: 320px;
  background: var(--neutral-50);
  border-left: 1px solid var(--neutral-200);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sources-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-md) var(--spacing-lg);
  border-bottom: 1px solid var(--neutral-200);
}

.sources-header h3 {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  font-size: 14px;
  font-weight: 600;
  margin: 0;
}

.sources-header h3 svg {
  width: 18px;
  height: 18px;
  color: var(--neutral-500);
}

.btn-close {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  color: var(--neutral-500);
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-close:hover {
  background: var(--neutral-100);
}

.btn-close svg {
  width: 16px;
  height: 16px;
}

.source-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--spacing-md);
}

.source-item {
  padding: var(--spacing-md);
  background: var(--neutral-50);
  border-radius: var(--radius-md);
  margin-bottom: var(--spacing-sm);
  border: 1px solid var(--neutral-100);
}

.source-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-sm);
}

.source-number {
  width: 20px;
  height: 20px;
  background: var(--primary-100);
  color: var(--primary-600);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
}

.source-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--neutral-700);
}

.source-content {
  font-size: 12px;
  color: var(--neutral-600);
  line-height: 1.6;
  margin-bottom: var(--spacing-sm);
}

.source-meta {
  display: flex;
  align-items: center;
}

.relevance-score {
  font-size: 11px;
  color: var(--neutral-500);
}

/* Transitions */
.slide-enter-active,
.slide-leave-active {
  transition: all var(--transition-normal);
}

.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
  opacity: 0;
}

/* Responsive */
@media (max-width: 768px) {
  .sources-panel {
    position: fixed;
    right: 0;
    top: 0;
    bottom: 0;
    z-index: 50;
    box-shadow: var(--shadow-xl);
  }
}
</style>
