<template>
  <div class="login">
    <div class="login-card">
      <h1>装备智能测试一体化平台</h1>
      <p>从需求到修复的全链路智能验证平台</p>
      
      <h2 class="form-title">{{ isRegister ? '注册账号' : '用户登录' }}</h2>
      
      <form class="form" @submit.prevent="handleSubmit">
        <div class="form-group">
          <label>账号</label>
          <input v-model="account" type="text" placeholder="请输入账号" />
        </div>
        <div class="form-group">
          <label>密码</label>
          <input v-model="password" type="password" placeholder="请输入密码" />
        </div>
        
        <!-- 注册时的确认密码 -->
        <div class="form-group" v-if="isRegister">
          <label>确认密码</label>
          <input v-model="confirmPassword" type="password" placeholder="请再次输入密码" />
        </div>

        <span class="error" v-if="errorMessage">{{ errorMessage }}</span>
        
        <button class="btn" type="submit">
          {{ isRegister ? '立即注册' : '登录' }}
        </button>
      </form>

      <div class="toggle-section">
        <p v-if="!isRegister">
          还没有账号？
          <span class="toggle-link" @click="toggleMode">立即注册</span>
        </p>
        <p v-else>
          已有账号？
          <span class="toggle-link" @click="toggleMode">去登录</span>
        </p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { setToken, setUserName } from '../../utils/auth'
import { login, register } from '../../api/auth'

const route = useRoute()
const router = useRouter()
const account = ref('')
const password = ref('')
const confirmPassword = ref('')
const errorMessage = ref('')
const isRegister = ref(false)

const toggleMode = () => {
  isRegister.value = !isRegister.value
  errorMessage.value = ''
  account.value = ''
  password.value = ''
  confirmPassword.value = ''
}

const handleSubmit = async () => {
  errorMessage.value = ''
  
  if (!account.value || !password.value) {
    errorMessage.value = '请输入账号和密码'
    return
  }

  try {
    if (isRegister.value) {
      // 注册逻辑
      if (password.value !== confirmPassword.value) {
        errorMessage.value = '两次输入的密码不一致'
        return
      }
      
      await register({
        username: account.value,
        password: password.value
      })

      alert('注册成功，请登录')
      toggleMode()
    } else {
      // 登录逻辑
      const res: any = await login({
        username: account.value,
        password: password.value
      })
      
      if (res.code === 200) {
        setToken(res.token)
        setUserName(account.value)
        const redirect = (route.query.redirect as string) || '/projects'
        router.push(redirect)
      }
    }
  } catch (err: any) {
    if (err.code === 404) {
      errorMessage.value = '账号不存在'
    } else if (err.code === 401) {
      errorMessage.value = '密码错误'
    } else {
      errorMessage.value = err.message || '操作失败'
    }
  }
}
</script>

<style scoped>
.login {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0f172a, #1e3a8a);
  padding: 20px;
}

.login-card {
  width: 100%;
  max-width: 400px;
  background: #ffffff;
  padding: 40px;
  border-radius: 16px;
  box-shadow: 0 20px 40px rgba(15, 23, 42, 0.3);
  text-align: center;
}

.login-card h1 {
  margin: 0 0 8px;
  font-size: 24px;
  color: #1e293b;
}

.login-card p {
  margin: 0 0 24px;
  color: #64748b;
  font-size: 14px;
}

.form-title {
  margin: 0 0 24px;
  font-size: 18px;
  color: #334155;
  font-weight: 600;
}

.form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.form-group {
  text-align: left;
}

.form-group label {
  display: block;
  margin-bottom: 8px;
  font-size: 14px;
  color: #475569;
  font-weight: 500;
}

.form-group input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s;
  box-sizing: border-box;
}

.form-group input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
}

.error {
  color: #dc2626;
  font-size: 13px;
  text-align: left;
}

.btn {
  width: 100%;
  padding: 12px;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 16px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.btn:hover {
  background: #1d4ed8;
}

.toggle-section {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid #e2e8f0;
}

.toggle-section p {
  margin: 0;
  font-size: 14px;
  color: #64748b;
}

.toggle-link {
  color: #2563eb;
  font-weight: 500;
  cursor: pointer;
  margin-left: 4px;
  transition: color 0.2s;
}

.toggle-link:hover {
  color: #1d4ed8;
  text-decoration: underline;
}

/* 响应式调整 */
@media (max-width: 480px) {
  .login-card {
    padding: 24px;
  }
  
  .toggle-link {
    display: inline-block;
    padding: 4px; /* 增加触摸区域 */
  }
}
</style>
