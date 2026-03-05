/// <reference types="../../node_modules/.vue-global-types/vue_3.5_0_0_0.d.ts" />
import { computed } from 'vue';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { RadarChart } from 'echarts/charts';
import { TitleComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import VChart from 'vue-echarts';
import RingChart from './charts/RingChart.vue';
import BarChart from './charts/BarChart.vue';
import LineChart from './charts/LineChart.vue';
import StatCard from './dashboard/StatCard.vue';
import { Activity, AlertCircle, Bug, CheckCircle, Clock, Code, FileText, Grid, ShieldCheck, Timer } from 'lucide-vue-next';
// 注册 ECharts 组件
use([CanvasRenderer, RadarChart, TitleComponent, TooltipComponent, LegendComponent]);
const props = defineProps();
// 格式化数值工具函数
const formatValue = (value, unit) => {
    if (value === null || value === undefined)
        return '- -';
    if (unit === '%')
        return `${value}%`;
    if (unit === '小时/天' || unit === '天' || unit === '小时') {
        return `${Number.isInteger(value) ? value : value.toFixed(1)} ${unit}`;
    }
    return `${value} ${unit}`;
};
const radarOption = computed(() => {
    const values = props.data?.radarData || [0, 0, 0, 0, 0, 0];
    const isEmpty = !props.data || !props.data.radarData || props.data.radarData.length === 0;
    return {
        tooltip: {},
        radar: {
            indicator: [
                { name: '需求与文档健康度', max: 100 },
                { name: '代码质量', max: 100 },
                { name: '单元测试', max: 100 },
                { name: '集成测试', max: 100 },
                { name: '缺陷闭环', max: 100 },
                { name: '安全质量', max: 100 }
            ],
            radius: '65%',
            center: ['50%', '50%']
        },
        series: [
            {
                name: '工程质量维度',
                type: 'radar',
                data: [
                    {
                        value: isEmpty ? [0, 0, 0, 0, 0, 0] : values,
                        name: '当前工程'
                    }
                ],
                itemStyle: {
                    color: '#5470c6'
                },
                areaStyle: {
                    opacity: 0.2
                }
            }
        ]
    };
});
debugger; /* PartiallyEnd: #3632/scriptSetup.vue */
const __VLS_ctx = {};
let __VLS_components;
let __VLS_directives;
/** @type {__VLS_StyleScopedClasses['card-wrapper']} */ ;
/** @type {__VLS_StyleScopedClasses['charts-row']} */ ;
/** @type {__VLS_StyleScopedClasses['cards-row']} */ ;
/** @type {__VLS_StyleScopedClasses['wide']} */ ;
// CSS variable injection 
// CSS variable injection end 
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "dashboard-section" },
});
__VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
    ...{ class: "section-title" },
});
if (__VLS_ctx.loading) {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "loading-state" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "spinner" },
    });
}
else {
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "dashboard-layout" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "metric-section" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "metric-card score-card" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.h4, __VLS_intrinsicElements.h4)({});
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "score-value" },
    });
    (__VLS_ctx.formatValue(__VLS_ctx.data?.overallScore, '分'));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "separator" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "metric-section" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "metric-card radar-card" },
    });
    const __VLS_0 = {}.VChart;
    /** @type {[typeof __VLS_components.VChart, typeof __VLS_components.vChart, ]} */ ;
    // @ts-ignore
    const __VLS_1 = __VLS_asFunctionalComponent(__VLS_0, new __VLS_0({
        ...{ class: "chart" },
        option: (__VLS_ctx.radarOption),
        autoresize: true,
    }));
    const __VLS_2 = __VLS_1({
        ...{ class: "chart" },
        option: (__VLS_ctx.radarOption),
        autoresize: true,
    }, ...__VLS_functionalComponentArgsRest(__VLS_1));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "separator" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "metric-section" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "metric-header" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "charts-row" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "chart-wrapper" },
    });
    /** @type {[typeof RingChart, ]} */ ;
    // @ts-ignore
    const __VLS_4 = __VLS_asFunctionalComponent(RingChart, new RingChart({
        title: "需求覆盖率",
        data: ({
            total: 100,
            completed: __VLS_ctx.data?.metrics.requirements.coverage || 0,
            passed: __VLS_ctx.data?.metrics.requirements.coverage || 0,
            passRate: __VLS_ctx.data?.metrics.requirements.coverage || 0
        }),
    }));
    const __VLS_5 = __VLS_4({
        title: "需求覆盖率",
        data: ({
            total: 100,
            completed: __VLS_ctx.data?.metrics.requirements.coverage || 0,
            passed: __VLS_ctx.data?.metrics.requirements.coverage || 0,
            passRate: __VLS_ctx.data?.metrics.requirements.coverage || 0
        }),
    }, ...__VLS_functionalComponentArgsRest(__VLS_4));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "chart-wrapper" },
    });
    /** @type {[typeof RingChart, ]} */ ;
    // @ts-ignore
    const __VLS_7 = __VLS_asFunctionalComponent(RingChart, new RingChart({
        title: "文档健康度",
        data: ({
            total: 100,
            completed: __VLS_ctx.data?.metrics.requirements.health || 0,
            passed: __VLS_ctx.data?.metrics.requirements.health || 0,
            passRate: __VLS_ctx.data?.metrics.requirements.health || 0
        }),
    }));
    const __VLS_8 = __VLS_7({
        title: "文档健康度",
        data: ({
            total: 100,
            completed: __VLS_ctx.data?.metrics.requirements.health || 0,
            passed: __VLS_ctx.data?.metrics.requirements.health || 0,
            passRate: __VLS_ctx.data?.metrics.requirements.health || 0
        }),
    }, ...__VLS_functionalComponentArgsRest(__VLS_7));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "separator" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "metric-section" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "metric-header" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "cards-row" },
    });
    /** @type {[typeof StatCard, ]} */ ;
    // @ts-ignore
    const __VLS_10 = __VLS_asFunctionalComponent(StatCard, new StatCard({
        title: "代码缺陷",
        value: (__VLS_ctx.formatValue(__VLS_ctx.data?.metrics.codeQuality.bugs, '个')),
        icon: (__VLS_ctx.Bug),
        color: "red",
    }));
    const __VLS_11 = __VLS_10({
        title: "代码缺陷",
        value: (__VLS_ctx.formatValue(__VLS_ctx.data?.metrics.codeQuality.bugs, '个')),
        icon: (__VLS_ctx.Bug),
        color: "red",
    }, ...__VLS_functionalComponentArgsRest(__VLS_10));
    /** @type {[typeof StatCard, ]} */ ;
    // @ts-ignore
    const __VLS_13 = __VLS_asFunctionalComponent(StatCard, new StatCard({
        title: "安全漏洞",
        value: (__VLS_ctx.formatValue(__VLS_ctx.data?.metrics.codeQuality.vulnerabilities, '个')),
        icon: (__VLS_ctx.ShieldCheck),
        color: "green",
    }));
    const __VLS_14 = __VLS_13({
        title: "安全漏洞",
        value: (__VLS_ctx.formatValue(__VLS_ctx.data?.metrics.codeQuality.vulnerabilities, '个')),
        icon: (__VLS_ctx.ShieldCheck),
        color: "green",
    }, ...__VLS_functionalComponentArgsRest(__VLS_13));
    /** @type {[typeof StatCard, ]} */ ;
    // @ts-ignore
    const __VLS_16 = __VLS_asFunctionalComponent(StatCard, new StatCard({
        title: "技术债务",
        value: (__VLS_ctx.formatValue(__VLS_ctx.data?.metrics.codeQuality.debt, '小时')),
        icon: (__VLS_ctx.Clock),
        color: "orange",
    }));
    const __VLS_17 = __VLS_16({
        title: "技术债务",
        value: (__VLS_ctx.formatValue(__VLS_ctx.data?.metrics.codeQuality.debt, '小时')),
        icon: (__VLS_ctx.Clock),
        color: "orange",
    }, ...__VLS_functionalComponentArgsRest(__VLS_16));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "separator" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "metric-section" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "metric-header" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "charts-row mixed-row" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "chart-wrapper" },
    });
    /** @type {[typeof RingChart, ]} */ ;
    // @ts-ignore
    const __VLS_19 = __VLS_asFunctionalComponent(RingChart, new RingChart({
        title: "覆盖率",
        data: ({
            total: 100,
            completed: __VLS_ctx.data?.metrics.unitTest.coverage || 0,
            passed: __VLS_ctx.data?.metrics.unitTest.coverage || 0,
            passRate: __VLS_ctx.data?.metrics.unitTest.coverage || 0
        }),
    }));
    const __VLS_20 = __VLS_19({
        title: "覆盖率",
        data: ({
            total: 100,
            completed: __VLS_ctx.data?.metrics.unitTest.coverage || 0,
            passed: __VLS_ctx.data?.metrics.unitTest.coverage || 0,
            passRate: __VLS_ctx.data?.metrics.unitTest.coverage || 0
        }),
    }, ...__VLS_functionalComponentArgsRest(__VLS_19));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "chart-wrapper" },
    });
    /** @type {[typeof RingChart, ]} */ ;
    // @ts-ignore
    const __VLS_22 = __VLS_asFunctionalComponent(RingChart, new RingChart({
        title: "通过率",
        data: ({
            total: 100,
            completed: 100,
            passed: __VLS_ctx.data?.metrics.unitTest.passRate || 0,
            passRate: __VLS_ctx.data?.metrics.unitTest.passRate || 0
        }),
    }));
    const __VLS_23 = __VLS_22({
        title: "通过率",
        data: ({
            total: 100,
            completed: 100,
            passed: __VLS_ctx.data?.metrics.unitTest.passRate || 0,
            passRate: __VLS_ctx.data?.metrics.unitTest.passRate || 0
        }),
    }, ...__VLS_functionalComponentArgsRest(__VLS_22));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "card-wrapper" },
    });
    /** @type {[typeof StatCard, ]} */ ;
    // @ts-ignore
    const __VLS_25 = __VLS_asFunctionalComponent(StatCard, new StatCard({
        title: "执行耗时",
        value: (__VLS_ctx.formatValue(__VLS_ctx.data?.metrics.unitTest.duration, '秒')),
        icon: (__VLS_ctx.Timer),
        color: "blue",
    }));
    const __VLS_26 = __VLS_25({
        title: "执行耗时",
        value: (__VLS_ctx.formatValue(__VLS_ctx.data?.metrics.unitTest.duration, '秒')),
        icon: (__VLS_ctx.Timer),
        color: "blue",
    }, ...__VLS_functionalComponentArgsRest(__VLS_25));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "separator" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "metric-section" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "metric-header" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "charts-row" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "chart-wrapper" },
    });
    /** @type {[typeof BarChart, ]} */ ;
    // @ts-ignore
    const __VLS_28 = __VLS_asFunctionalComponent(BarChart, new BarChart({
        title: "测试用例的维度构成情况",
        data: ([
            { name: '功能', value: 40 },
            { name: '性能', value: 30 },
            { name: '边界', value: 20 },
            { name: '接口', value: 50 },
            { name: '兼容', value: 25 },
            { name: '稳定性', value: 35 },
            { name: '可用性', value: 45 },
            { name: '安全性', value: 15 }
        ]),
    }));
    const __VLS_29 = __VLS_28({
        title: "测试用例的维度构成情况",
        data: ([
            { name: '功能', value: 40 },
            { name: '性能', value: 30 },
            { name: '边界', value: 20 },
            { name: '接口', value: 50 },
            { name: '兼容', value: 25 },
            { name: '稳定性', value: 35 },
            { name: '可用性', value: 45 },
            { name: '安全性', value: 15 }
        ]),
    }, ...__VLS_functionalComponentArgsRest(__VLS_28));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "chart-wrapper" },
    });
    /** @type {[typeof RingChart, ]} */ ;
    // @ts-ignore
    const __VLS_31 = __VLS_asFunctionalComponent(RingChart, new RingChart({
        title: "软件集成测试用例执行情况",
        data: ({
            total: 1000,
            completed: 850,
            passed: 800,
            passRate: 94.1
        }),
        icon: (__VLS_ctx.Code),
    }));
    const __VLS_32 = __VLS_31({
        title: "软件集成测试用例执行情况",
        data: ({
            total: 1000,
            completed: 850,
            passed: 800,
            passRate: 94.1
        }),
        icon: (__VLS_ctx.Code),
    }, ...__VLS_functionalComponentArgsRest(__VLS_31));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "chart-wrapper" },
    });
    /** @type {[typeof RingChart, ]} */ ;
    // @ts-ignore
    const __VLS_34 = __VLS_asFunctionalComponent(RingChart, new RingChart({
        title: "软/硬件集成测试用例执行情况",
        data: ({
            total: 500,
            completed: 480,
            passed: 470,
            passRate: 97.9
        }),
        icon: (__VLS_ctx.ShieldCheck),
    }));
    const __VLS_35 = __VLS_34({
        title: "软/硬件集成测试用例执行情况",
        data: ({
            total: 500,
            completed: 480,
            passed: 470,
            passRate: 97.9
        }),
        icon: (__VLS_ctx.ShieldCheck),
    }, ...__VLS_functionalComponentArgsRest(__VLS_34));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "separator-dashed" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "cards-row" },
    });
    /** @type {[typeof StatCard, ]} */ ;
    // @ts-ignore
    const __VLS_37 = __VLS_asFunctionalComponent(StatCard, new StatCard({
        title: "测试文件数",
        value: "45",
        icon: (__VLS_ctx.FileText),
        color: "blue",
    }));
    const __VLS_38 = __VLS_37({
        title: "测试文件数",
        value: "45",
        icon: (__VLS_ctx.FileText),
        color: "blue",
    }, ...__VLS_functionalComponentArgsRest(__VLS_37));
    /** @type {[typeof StatCard, ]} */ ;
    // @ts-ignore
    const __VLS_40 = __VLS_asFunctionalComponent(StatCard, new StatCard({
        title: "总用例数",
        value: "1500",
        icon: (__VLS_ctx.Grid),
        color: "cyan",
    }));
    const __VLS_41 = __VLS_40({
        title: "总用例数",
        value: "1500",
        icon: (__VLS_ctx.Grid),
        color: "cyan",
    }, ...__VLS_functionalComponentArgsRest(__VLS_40));
    /** @type {[typeof StatCard, ]} */ ;
    // @ts-ignore
    const __VLS_43 = __VLS_asFunctionalComponent(StatCard, new StatCard({
        title: "当前失败用例数",
        value: "15",
        icon: (__VLS_ctx.AlertCircle),
        color: "red",
    }));
    const __VLS_44 = __VLS_43({
        title: "当前失败用例数",
        value: "15",
        icon: (__VLS_ctx.AlertCircle),
        color: "red",
    }, ...__VLS_functionalComponentArgsRest(__VLS_43));
    /** @type {[typeof StatCard, ]} */ ;
    // @ts-ignore
    const __VLS_46 = __VLS_asFunctionalComponent(StatCard, new StatCard({
        title: "已修复失败用例数",
        value: "120",
        icon: (__VLS_ctx.CheckCircle),
        color: "green",
    }));
    const __VLS_47 = __VLS_46({
        title: "已修复失败用例数",
        value: "120",
        icon: (__VLS_ctx.CheckCircle),
        color: "green",
    }, ...__VLS_functionalComponentArgsRest(__VLS_46));
    /** @type {[typeof StatCard, ]} */ ;
    // @ts-ignore
    const __VLS_49 = __VLS_asFunctionalComponent(StatCard, new StatCard({
        title: "当前失效用例数",
        value: "8",
        icon: (__VLS_ctx.Clock),
        color: "orange",
    }));
    const __VLS_50 = __VLS_49({
        title: "当前失效用例数",
        value: "8",
        icon: (__VLS_ctx.Clock),
        color: "orange",
    }, ...__VLS_functionalComponentArgsRest(__VLS_49));
    /** @type {[typeof StatCard, ]} */ ;
    // @ts-ignore
    const __VLS_52 = __VLS_asFunctionalComponent(StatCard, new StatCard({
        title: "已修复失效用例数",
        value: "5",
        icon: (__VLS_ctx.ShieldCheck),
        color: "green",
    }));
    const __VLS_53 = __VLS_52({
        title: "已修复失效用例数",
        value: "5",
        icon: (__VLS_ctx.ShieldCheck),
        color: "green",
    }, ...__VLS_functionalComponentArgsRest(__VLS_52));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "separator-dashed" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "chart-wrapper wide" },
        ...{ style: {} },
    });
    /** @type {[typeof LineChart, ]} */ ;
    // @ts-ignore
    const __VLS_55 = __VLS_asFunctionalComponent(LineChart, new LineChart({
        title: "测试执行趋势分析",
        data: ([
            { date: '2023-10-01', passed: 120, failed: 20 },
            { date: '2023-10-02', passed: 132, failed: 18 },
            { date: '2023-10-03', passed: 101, failed: 19 },
            { date: '2023-10-04', passed: 134, failed: 23 },
            { date: '2023-10-05', passed: 90, failed: 29 },
            { date: '2023-10-06', passed: 230, failed: 33 },
            { date: '2023-10-07', passed: 210, failed: 31 }
        ]),
    }));
    const __VLS_56 = __VLS_55({
        title: "测试执行趋势分析",
        data: ([
            { date: '2023-10-01', passed: 120, failed: 20 },
            { date: '2023-10-02', passed: 132, failed: 18 },
            { date: '2023-10-03', passed: 101, failed: 19 },
            { date: '2023-10-04', passed: 134, failed: 23 },
            { date: '2023-10-05', passed: 90, failed: 29 },
            { date: '2023-10-06', passed: 230, failed: 33 },
            { date: '2023-10-07', passed: 210, failed: 31 }
        ]),
    }, ...__VLS_functionalComponentArgsRest(__VLS_55));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "separator" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "metric-section" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "metric-header" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "charts-row mixed-row" },
    });
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "chart-wrapper wide" },
    });
    /** @type {[typeof BarChart, ]} */ ;
    // @ts-ignore
    const __VLS_58 = __VLS_asFunctionalComponent(BarChart, new BarChart({
        title: "缺陷状态分布",
        data: ([
            { name: '待修复', value: __VLS_ctx.data?.metrics.defect.open || 0 },
            { name: '已修复', value: __VLS_ctx.data?.metrics.defect.closed || 0 }
        ]),
    }));
    const __VLS_59 = __VLS_58({
        title: "缺陷状态分布",
        data: ([
            { name: '待修复', value: __VLS_ctx.data?.metrics.defect.open || 0 },
            { name: '已修复', value: __VLS_ctx.data?.metrics.defect.closed || 0 }
        ]),
    }, ...__VLS_functionalComponentArgsRest(__VLS_58));
    __VLS_asFunctionalElement(__VLS_intrinsicElements.div, __VLS_intrinsicElements.div)({
        ...{ class: "card-wrapper" },
    });
    /** @type {[typeof StatCard, ]} */ ;
    // @ts-ignore
    const __VLS_61 = __VLS_asFunctionalComponent(StatCard, new StatCard({
        title: "平均修复时间",
        value: (__VLS_ctx.formatValue(__VLS_ctx.data?.metrics.defect.avgCloseTime, '天')),
        icon: (__VLS_ctx.Activity),
        color: "cyan",
    }));
    const __VLS_62 = __VLS_61({
        title: "平均修复时间",
        value: (__VLS_ctx.formatValue(__VLS_ctx.data?.metrics.defect.avgCloseTime, '天')),
        icon: (__VLS_ctx.Activity),
        color: "cyan",
    }, ...__VLS_functionalComponentArgsRest(__VLS_61));
}
/** @type {__VLS_StyleScopedClasses['dashboard-section']} */ ;
/** @type {__VLS_StyleScopedClasses['section-title']} */ ;
/** @type {__VLS_StyleScopedClasses['loading-state']} */ ;
/** @type {__VLS_StyleScopedClasses['spinner']} */ ;
/** @type {__VLS_StyleScopedClasses['dashboard-layout']} */ ;
/** @type {__VLS_StyleScopedClasses['metric-section']} */ ;
/** @type {__VLS_StyleScopedClasses['metric-card']} */ ;
/** @type {__VLS_StyleScopedClasses['score-card']} */ ;
/** @type {__VLS_StyleScopedClasses['score-value']} */ ;
/** @type {__VLS_StyleScopedClasses['separator']} */ ;
/** @type {__VLS_StyleScopedClasses['metric-section']} */ ;
/** @type {__VLS_StyleScopedClasses['metric-card']} */ ;
/** @type {__VLS_StyleScopedClasses['radar-card']} */ ;
/** @type {__VLS_StyleScopedClasses['chart']} */ ;
/** @type {__VLS_StyleScopedClasses['separator']} */ ;
/** @type {__VLS_StyleScopedClasses['metric-section']} */ ;
/** @type {__VLS_StyleScopedClasses['metric-header']} */ ;
/** @type {__VLS_StyleScopedClasses['charts-row']} */ ;
/** @type {__VLS_StyleScopedClasses['chart-wrapper']} */ ;
/** @type {__VLS_StyleScopedClasses['chart-wrapper']} */ ;
/** @type {__VLS_StyleScopedClasses['separator']} */ ;
/** @type {__VLS_StyleScopedClasses['metric-section']} */ ;
/** @type {__VLS_StyleScopedClasses['metric-header']} */ ;
/** @type {__VLS_StyleScopedClasses['cards-row']} */ ;
/** @type {__VLS_StyleScopedClasses['separator']} */ ;
/** @type {__VLS_StyleScopedClasses['metric-section']} */ ;
/** @type {__VLS_StyleScopedClasses['metric-header']} */ ;
/** @type {__VLS_StyleScopedClasses['charts-row']} */ ;
/** @type {__VLS_StyleScopedClasses['mixed-row']} */ ;
/** @type {__VLS_StyleScopedClasses['chart-wrapper']} */ ;
/** @type {__VLS_StyleScopedClasses['chart-wrapper']} */ ;
/** @type {__VLS_StyleScopedClasses['card-wrapper']} */ ;
/** @type {__VLS_StyleScopedClasses['separator']} */ ;
/** @type {__VLS_StyleScopedClasses['metric-section']} */ ;
/** @type {__VLS_StyleScopedClasses['metric-header']} */ ;
/** @type {__VLS_StyleScopedClasses['charts-row']} */ ;
/** @type {__VLS_StyleScopedClasses['chart-wrapper']} */ ;
/** @type {__VLS_StyleScopedClasses['chart-wrapper']} */ ;
/** @type {__VLS_StyleScopedClasses['chart-wrapper']} */ ;
/** @type {__VLS_StyleScopedClasses['separator-dashed']} */ ;
/** @type {__VLS_StyleScopedClasses['cards-row']} */ ;
/** @type {__VLS_StyleScopedClasses['separator-dashed']} */ ;
/** @type {__VLS_StyleScopedClasses['chart-wrapper']} */ ;
/** @type {__VLS_StyleScopedClasses['wide']} */ ;
/** @type {__VLS_StyleScopedClasses['separator']} */ ;
/** @type {__VLS_StyleScopedClasses['metric-section']} */ ;
/** @type {__VLS_StyleScopedClasses['metric-header']} */ ;
/** @type {__VLS_StyleScopedClasses['charts-row']} */ ;
/** @type {__VLS_StyleScopedClasses['mixed-row']} */ ;
/** @type {__VLS_StyleScopedClasses['chart-wrapper']} */ ;
/** @type {__VLS_StyleScopedClasses['wide']} */ ;
/** @type {__VLS_StyleScopedClasses['card-wrapper']} */ ;
var __VLS_dollars;
const __VLS_self = (await import('vue')).defineComponent({
    setup() {
        return {
            VChart: VChart,
            RingChart: RingChart,
            BarChart: BarChart,
            LineChart: LineChart,
            StatCard: StatCard,
            Activity: Activity,
            AlertCircle: AlertCircle,
            Bug: Bug,
            CheckCircle: CheckCircle,
            Clock: Clock,
            Code: Code,
            FileText: FileText,
            Grid: Grid,
            ShieldCheck: ShieldCheck,
            Timer: Timer,
            formatValue: formatValue,
            radarOption: radarOption,
        };
    },
    __typeProps: {},
});
export default (await import('vue')).defineComponent({
    setup() {
        return {};
    },
    __typeProps: {},
});
; /* PartiallyEnd: #4569/main.vue */
