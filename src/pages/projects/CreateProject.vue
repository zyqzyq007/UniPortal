<template>
  <div class="container">
    <div class="breadcrumb">
        <RouterLink to="/projects" class="breadcrumb-link">工程列表</RouterLink>
        <span class="separator">/</span>
        <span class="current">新建测试工程</span>
    </div>

    <div class="form-card">
        <h2>新建测试工程</h2>
        <form @submit.prevent="handleSubmit">
            <div class="form-group">
                <label for="name">工程名称 <span class="required">*</span></label>
                <div class="input-wrapper">
                    <input 
                        id="name" 
                        v-model="form.name" 
                        type="text" 
                        placeholder="请输入工程名称" 
                        :class="{ 'has-error': errors.name }"
                        maxlength="64"
                        @input="validateName"
                    />
                    <span class="char-count">{{ form.name.length }}/64</span>
                </div>
                <span class="error-msg" v-if="errors.name">{{ errors.name }}</span>
                <p class="hint">支持中文、字母、数字、下划线</p>
            </div>

            <div class="form-group">
                <label for="description">工程描述</label>
                <div class="input-wrapper">
                    <textarea 
                        id="description" 
                        v-model="form.description" 
                        placeholder="请输入工程描述（选填）" 
                        rows="4"
                        maxlength="500"
                    ></textarea>
                    <span class="char-count">{{ form.description.length }}/500</span>
                </div>
            </div>

            <div class="form-actions">
                <button type="button" class="btn-cancel" @click="router.back()">取消</button>
                <button type="submit" class="btn-submit" :disabled="isSubmitting">
                    {{ isSubmitting ? '创建中...' : '创建工程' }}
                </button>
            </div>
        </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { createProject } from '../../api/projects'

const router = useRouter()
const isSubmitting = ref(false)

const form = reactive({
    name: '',
    description: ''
})

const errors = reactive({
    name: ''
})

const validateName = () => {
    errors.name = ''
    if (!form.name.trim()) {
        errors.name = '工程名称不能为空'
        return false
    }
    const nameRegex = /^[\u4e00-\u9fa5a-zA-Z0-9_]+$/
    if (!nameRegex.test(form.name)) {
        errors.name = '工程名称仅支持中文、字母、数字、下划线'
        return false
    }
    return true
}

const handleSubmit = async () => {
    if (!validateName()) return

    try {
        isSubmitting.value = true
        const res: any = await createProject({
            name: form.name,
            description: form.description
        })

        if (res.code === 201) {
            // Success, navigate to overview
            router.push(`/projects/${res.data.project_id}/overview`)
        } else {
            alert(res.message || '创建失败')
        }
    } catch (error) {
        console.error('Create project failed', error)
        alert('创建失败，请重试')
    } finally {
        isSubmitting.value = false
    }
}
</script>

<style scoped>
.container {
    padding: 24px;
    max-width: 800px;
    margin: 0 auto;
}

.breadcrumb {
    margin-bottom: 24px;
    font-size: 14px;
    color: #64748b;
    display: flex;
    align-items: center;
}

.breadcrumb-link {
    color: #64748b;
    text-decoration: none;
    transition: color 0.2s;
}

.breadcrumb-link:hover {
    color: #1e40af;
}

.separator {
    margin: 0 8px;
    color: #cbd5e1;
}

.current {
    color: #1e293b;
    font-weight: 500;
}

.form-card {
    background: white;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 32px;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}

h2 {
    margin: 0 0 24px 0;
    font-size: 20px;
    color: #1e293b;
    font-weight: 600;
}

.form-group {
    margin-bottom: 24px;
}

label {
    display: block;
    margin-bottom: 8px;
    font-size: 14px;
    font-weight: 500;
    color: #334155;
}

.required {
    color: #ef4444;
    margin-left: 4px;
}

.input-wrapper {
    position: relative;
}

input[type="text"],
textarea {
    width: 100%;
    padding: 10px 12px;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    font-size: 14px;
    color: #1e293b;
    outline: none;
    transition: border-color 0.2s;
    box-sizing: border-box;
}

textarea {
    resize: vertical;
    min-height: 100px;
}

input[type="text"]:focus,
textarea:focus {
    border-color: #3b82f6;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.has-error {
    border-color: #ef4444 !important;
}

.error-msg {
    display: block;
    margin-top: 6px;
    color: #ef4444;
    font-size: 12px;
}

.hint {
    margin: 6px 0 0;
    color: #94a3b8;
    font-size: 12px;
}

.char-count {
    position: absolute;
    right: 12px;
    bottom: 10px;
    font-size: 12px;
    color: #94a3b8;
    pointer-events: none;
}

.form-actions {
    display: flex;
    justify-content: flex-end;
    gap: 16px;
    margin-top: 32px;
    padding-top: 24px;
    border-top: 1px solid #f1f5f9;
}

.btn-cancel {
    padding: 10px 24px;
    background: white;
    border: 1px solid #cbd5e1;
    color: #64748b;
    border-radius: 8px;
    font-size: 14px;
    cursor: pointer;
    transition: all 0.2s;
}

.btn-cancel:hover {
    background: #f8fafc;
    color: #1e293b;
}

.btn-submit {
    padding: 10px 24px;
    background: #1e40af;
    border: none;
    color: white;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.2s;
}

.btn-submit:hover {
    background: #1e3a8a;
}

.btn-submit:disabled {
    background: #93c5fd;
    cursor: not-allowed;
}
</style>
