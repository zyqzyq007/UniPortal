/// <reference types="../../../node_modules/.vue-global-types/vue_3.5_0_0_0.d.ts" />
import { ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { setToken, setUserName } from '../../utils/auth';
import { login, register } from '../../api/auth';
const route = useRoute();
const router = useRouter();
const account = ref('');
const password = ref('');
const confirmPassword = ref('');
const errorMessage = ref('');
const isRegister = ref(false);
const toggleMode = () => {
    isRegister.value = !isRegister.value;
    errorMessage.value = '';
    account.value = '';
    password.value = '';
    confirmPassword.value = '';
};
const handleSubmit = async () => {
    errorMessage.value = '';
    if (!account.value || !password.value) {
        errorMessage.value = '请输入账号和密码';
        return;
    }
    try {
        if (isRegister.value) {
            // 注册逻辑
            if (password.value !== confirmPassword.value) {
                errorMessage.value = '两次输入的密码不一致';
                return;
            }
            await register({
                username: account.value,
                password: password.value
            });
            alert('注册成功，请登录');
            toggleMode();
        }
        else {
            // 登录逻辑
            const res = await login({
                username: account.value,
                password: password.value
            });
            if (res.code === 200) {
                setToken(res.token);
                setUserName(account.value);
                const redirect = route.query.redirect || '/projects';
                router.push(redirect);
            }
        }
    }
    catch (err) {
        if (err.code === 404) {
            errorMessage.value = '账号不存在';
        }
        else if (err.code === 401) {
            errorMessage.value = '密码错误';
        }
        else {
            errorMessage.value = err.message || '操作失败';
        }
    }
};
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
/** @type {__VLS_StyleScopedClasses['login-card']} */ ;
/** @type {__VLS_StyleScopedClasses['login-card']} */ ;
/** @type {__VLS_StyleScopedClasses['form-group']} */ ;
/** @type {__VLS_StyleScopedClasses['form-group']} */ ;
/** @type {__VLS_StyleScopedClasses['form-group']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
/** @type {__VLS_StyleScopedClasses['toggle-section']} */ ;
/** @type {__VLS_StyleScopedClasses['toggle-link']} */ ;
/** @type {__VLS_StyleScopedClasses['login-card']} */ ;
/** @type {__VLS_StyleScopedClasses['toggle-link']} */ ;
// CSS variable injection 
// CSS variable injection end 
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "login" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "login-card" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.h1, __VLS_intrinsicElements.h1)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.h2, __VLS_intrinsicElements.h2)({
    ...{ class: "form-title" },
});
(__VLS_ctx.isRegister ? '注册账号' : '用户登录');
__VLS_asFunctionalElement(__VLS_intrinsicElements.form, __VLS_intrinsicElements.form)({
    ...{ onSubmit: (__VLS_ctx.handleSubmit) },
    ...{ class: "form" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "form-group" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.label, __VLS_intrinsicElements.label)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.input)({
    value: (__VLS_ctx.account),
    type: "text",
    placeholder: "请输入账号",
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "form-group" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.label, __VLS_intrinsicElements.label)({});
__VLS_asFunctionalElement(__VLS_intrinsicElements.input)({
    type: "password",
    placeholder: "请输入密码",
});
(__VLS_ctx.password);
if (__VLS_ctx.isRegister) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "form-group" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.label, __VLS_intrinsicElements.label)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.input)({
        type: "password",
        placeholder: "请再次输入密码",
    });
    (__VLS_ctx.confirmPassword);
}
if (__VLS_ctx.errorMessage) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ class: "error" },
    });
    (__VLS_ctx.errorMessage);
}
__VLS_asFunctionalElement(__VLS_intrinsicElements.button, __VLS_intrinsicElements.button)({
    ...{ class: "btn" },
    type: "submit",
});
(__VLS_ctx.isRegister ? '立即注册' : '登录');
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "toggle-section" },
});
if (!__VLS_ctx.isRegister) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ onClick: (__VLS_ctx.toggleMode) },
        ...{ class: "toggle-link" },
    });
}
else {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.p, __VLS_intrinsicElements.p)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.span, __VLS_intrinsicElements.span)({
        ...{ onClick: (__VLS_ctx.toggleMode) },
        ...{ class: "toggle-link" },
    });
}
/** @type {__VLS_StyleScopedClasses['login']} */ ;
/** @type {__VLS_StyleScopedClasses['login-card']} */ ;
/** @type {__VLS_StyleScopedClasses['form-title']} */ ;
/** @type {__VLS_StyleScopedClasses['form']} */ ;
/** @type {__VLS_StyleScopedClasses['form-group']} */ ;
/** @type {__VLS_StyleScopedClasses['form-group']} */ ;
/** @type {__VLS_StyleScopedClasses['form-group']} */ ;
/** @type {__VLS_StyleScopedClasses['error']} */ ;
/** @type {__VLS_StyleScopedClasses['btn']} */ ;
/** @type {__VLS_StyleScopedClasses['toggle-section']} */ ;
/** @type {__VLS_StyleScopedClasses['toggle-link']} */ ;
/** @type {__VLS_StyleScopedClasses['toggle-link']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            account: account,
            password: password,
            confirmPassword: confirmPassword,
            errorMessage: errorMessage,
            isRegister: isRegister,
            toggleMode: toggleMode,
            handleSubmit: handleSubmit,
        };
    },
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
});
; /* PartiallyEnd: #4569/main.vue */
