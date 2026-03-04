<template>
  <div class="user-profile">
    <header class="topbar">
      <div class="topbar-left">
        <div class="brand">智能装备测试一体化平台</div>
      </div>
      <div class="topbar-right">
        <button class="link" @click="handleGoBack">返回</button>
      </div>
    </header>
    
    <div class="content">
      <div class="card profile-card">
        <h2 class="title">个人中心</h2>
        
        <div class="profile-header">
          <div class="avatar-wrapper" @click="triggerUpload">
            <img v-if="avatar" :src="avatar" class="avatar" />
            <div v-else class="avatar placeholder">{{ username[0]?.toUpperCase() }}</div>
            <div class="avatar-overlay">更换头像</div>
            <input
              type="file"
              ref="fileInput"
              accept="image/*"
              class="hidden-input"
              @change="handleAvatarUpload"
            />
          </div>
          <div class="user-info">
            <h3 class="username">{{ username }}</h3>
            <p class="role">管理员</p>
          </div>
        </div>

        <div class="form-section">
          <div class="form-item">
            <label>用户名</label>
            <input type="text" :value="username" disabled class="input disabled" />
          </div>
          <div class="form-item">
            <label>邮箱</label>
            <input type="email" v-model="email" class="input" placeholder="请输入邮箱" />
          </div>
        </div>

        <div class="actions-section">
          <button class="btn btn-outline" @click="startChangePassword">修改密码</button>
          <button class="btn btn-outline" @click="startSwitchAccount">切换账号</button>
          <button class="btn btn-danger" @click="handleLogout">退出登录</button>
        </div>

        <div class="page-footer">
          <button class="btn btn-secondary" @click="handleGoBack">返回</button>
          <button class="btn btn-primary" @click="saveProfile" :disabled="!isChanged">保存修改</button>
        </div>
      </div>
    </div>

    <!-- 弹窗遮罩 -->
    <Transition name="fade">
      <div v-if="currentDialog" class="dialog-overlay">
        <!-- 修改密码弹窗 -->
        <div v-if="currentDialog === 'password'" class="dialog-box">
          <h3 class="dialog-title">{{ passwordStep === 1 ? '验证原密码' : '设置新密码' }}</h3>
          <div class="dialog-content">
            <div class="form-item">
              <label>{{ passwordStep === 1 ? '原密码' : '新密码' }}</label>
              <input 
                type="password" 
                v-model="passwordInput" 
                class="input" 
                :placeholder="passwordStep === 1 ? '请输入原密码' : '请输入新密码'"
                @keyup.enter="handlePasswordAction"
              />
              <p v-if="passwordError" class="error-text">{{ passwordError }}</p>
            </div>
          </div>
          <div class="dialog-footer">
            <button class="btn btn-outline" @click="closeDialog">取消</button>
            <button class="btn btn-primary" @click="handlePasswordAction">确定</button>
          </div>
        </div>

        <!-- 切换账号确认弹窗 -->
        <div v-if="currentDialog === 'switch'" class="dialog-box">
          <h3 class="dialog-title">确认切换账号</h3>
          <div class="dialog-content">
            <p>您确定要切换账号吗？未保存的更改将会丢失。</p>
          </div>
          <div class="dialog-footer">
            <button class="btn btn-outline" @click="closeDialog">取消</button>
            <button class="btn btn-primary" @click="confirmSwitchAccount">确认切换</button>
          </div>
        </div>

        <!-- 未保存修改提示弹窗 -->
        <div v-if="currentDialog === 'unsaved'" class="dialog-box">
          <h3 class="dialog-title">未保存的修改</h3>
          <div class="dialog-content">
            <p>您有未保存的修改，是否要保存？</p>
          </div>
          <div class="dialog-footer">
            <button class="btn btn-outline" @click="discardAndLeave">取消保存</button>
            <button class="btn btn-primary" @click="saveAndLeave">保存</button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { 
  getUserName, 
  getUserAvatar, 
  setUserAvatar, 
  getUserEmail, 
  setUserEmail, 
  clearToken, 
  clearUser 
} from '../../utils/auth'

const router = useRouter()
const username = ref(getUserName())
const avatar = ref(getUserAvatar())
const email = ref(getUserEmail())
const initialEmail = ref('')
const fileInput = ref<HTMLInputElement | null>(null)

// 弹窗状态
const currentDialog = ref<'password' | 'switch' | 'unsaved' | null>(null)
const passwordStep = ref(1)
const passwordInput = ref('')
const passwordError = ref('')

onMounted(() => {
  initialEmail.value = email.value
})

const isChanged = computed(() => email.value !== initialEmail.value)

const triggerUpload = () => {
  fileInput.value?.click()
}

const handleAvatarUpload = (event: Event) => {
  const input = event.target as HTMLInputElement
  if (input.files && input.files[0]) {
    const reader = new FileReader()
    reader.onload = (e) => {
      if (e.target?.result) {
        avatar.value = e.target.result as string
        setUserAvatar(avatar.value)
      }
    }
    reader.readAsDataURL(input.files[0])
  }
}

const handleGoBack = () => {
  if (isChanged.value) {
    currentDialog.value = 'unsaved'
  } else {
    router.back()
  }
}

const discardAndLeave = () => {
  router.back()
  closeDialog()
}

const saveAndLeave = () => {
  saveProfile()
  router.back()
  closeDialog()
}

const saveProfile = () => {
  setUserEmail(email.value)
  initialEmail.value = email.value
  alert('个人信息保存成功')
}

// 密码修改逻辑
const startChangePassword = () => {
  currentDialog.value = 'password'
  passwordStep.value = 1
  passwordInput.value = ''
  passwordError.value = ''
}

const handlePasswordAction = () => {
  passwordError.value = ''
  if (!passwordInput.value) {
    passwordError.value = '请输入密码'
    return
  }

  if (passwordStep.value === 1) {
    // 模拟验证原密码 (假设原密码为 "123456")
    if (passwordInput.value === '123456') {
      passwordStep.value = 2
      passwordInput.value = ''
    } else {
      passwordError.value = '原密码错误'
    }
  } else {
    // 保存新密码
    alert('密码修改成功')
    closeDialog()
  }
}

// 切换账号逻辑
const startSwitchAccount = () => {
  currentDialog.value = 'switch'
}

const confirmSwitchAccount = () => {
  handleLogout()
}

const closeDialog = () => {
  currentDialog.value = null
  passwordInput.value = ''
  passwordError.value = ''
}

const handleLogout = () => {
  clearToken()
  clearUser()
  router.push('/login')
}
</script>

<style scoped>
.user-profile {
  min-height: 100vh;
  background: #f1f5f9;
  display: flex;
  flex-direction: column;
}

.topbar {
  height: 64px;
  background: var(--color-primary-900);
  color: #f8fafc;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
}

.brand {
  font-size: 18px;
  font-weight: 700;
}

.link {
  background: transparent;
  border: none;
  color: #93c5fd;
  text-decoration: none;
  font-size: 14px;
  cursor: pointer;
  padding: 0;
}
.link:hover {
  text-decoration: underline;
}

.content {
  flex: 1;
  display: flex;
  justify-content: center;
  padding: 40px 20px;
}

.profile-card {
  width: 100%;
  max-width: 600px;
  background: white;
  border-radius: 12px;
  padding: 32px;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
  height: fit-content;
  position: relative;
}

.title {
  margin: 0 0 32px;
  font-size: 24px;
  color: #1e293b;
  text-align: center;
}

.profile-header {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 32px;
}

.avatar-wrapper {
  position: relative;
  width: 80px;
  height: 80px;
  border-radius: 50%;
  overflow: hidden;
  cursor: pointer;
  margin-bottom: 16px;
  border: 2px solid #e2e8f0;
}

.avatar {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.avatar.placeholder {
  background: #3b82f6;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
  font-weight: bold;
}

.avatar-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.5);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  opacity: 0;
  transition: opacity 0.2s;
}

.avatar-wrapper:hover .avatar-overlay {
  opacity: 1;
}

.hidden-input {
  display: none;
}

.user-info {
  text-align: center;
}

.username {
  margin: 0 0 4px;
  font-size: 18px;
  color: #0f172a;
}

.role {
  margin: 0;
  font-size: 13px;
  color: #64748b;
}

.form-section {
  display: flex;
  flex-direction: column;
  gap: 20px;
  margin-bottom: 32px;
}

.form-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-item label {
  font-size: 14px;
  color: #475569;
  font-weight: 500;
}

.input {
  padding: 10px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s;
}

.input:focus {
  border-color: #3b82f6;
}

.input.disabled {
  background: #f1f5f9;
  color: #64748b;
}

.error-text {
  color: #dc2626;
  font-size: 12px;
  margin: 0;
}

.actions-section {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  padding-top: 24px;
  border-top: 1px solid #e2e8f0;
  margin-bottom: 24px;
}

.page-footer {
  display: flex;
  justify-content: space-between;
  padding-top: 24px;
  border-top: 1px solid #e2e8f0;
}

.btn {
  padding: 10px 20px;
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
  border: none;
}

.btn-primary {
  background: #3b82f6;
  color: white;
}
.btn-primary:hover {
  background: #2563eb;
}
.btn-primary:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}

.btn-secondary {
  background: #f1f5f9;
  color: #475569;
}
.btn-secondary:hover {
  background: #e2e8f0;
}

.btn-outline {
  background: white;
  border: 1px solid #cbd5e1;
  color: #475569;
}
.btn-outline:hover {
  border-color: #94a3b8;
  background: #f8fafc;
}

.btn-danger {
  grid-column: span 2;
  background: #fee2e2;
  border: 1px solid #fecaca;
  color: #dc2626;
}
.btn-danger:hover {
  background: #fecaca;
}

/* 弹窗样式 */
.dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.dialog-box {
  background: white;
  width: 400px;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
  transform: translateY(0);
}

.dialog-title {
  margin: 0 0 16px;
  font-size: 18px;
  color: #1e293b;
  text-align: center;
}

.dialog-content {
  margin-bottom: 24px;
}

.dialog-content p {
  color: #64748b;
  text-align: center;
  line-height: 1.5;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

/* 动画 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
