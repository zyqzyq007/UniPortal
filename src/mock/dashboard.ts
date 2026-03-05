export interface DashboardData {
    overallScore: number | null; // 项目总体质量评分
    radarData: number[]; // 六维雷达图数据 [需求与文档, 代码质量, 单元测试, 集成测试, 缺陷闭环, 安全质量]
    metrics: {
        requirements: {
            coverage: number | null; // 需求覆盖率 %
            health: number | null; // 文档健康度 分
        };
        codeQuality: {
            bugs: number | null; // 代码缺陷 个
            vulnerabilities: number | null; // 安全漏洞 个
            debt: number | null; // 技术债务 小时
        };
        unitTest: {
            coverage: number | null; // 单元测试覆盖率 %
            passRate: number | null; // 通过率 %
            duration: number | null; // 执行耗时 秒
        };
        integrationTest: {
            coverage: number | null; // 集成测试覆盖率 %
            passRate: number | null; // 通过率 %
        };
        defect: {
            open: number | null; // 待修复缺陷 个
            closed: number | null; // 已修复缺陷 个
            avgCloseTime: number | null; // 平均修复时间 小时/天
        };
    };
}

export const mockDashboardData: DashboardData = {
    overallScore: 85.5,
    radarData: [90, 85, 70, 60, 95, 80],
    metrics: {
        requirements: {
            coverage: 92.5,
            health: 88
        },
        codeQuality: {
            bugs: 12,
            vulnerabilities: 0,
            debt: 4.5
        },
        unitTest: {
            coverage: 78.2,
            passRate: 99.1,
            duration: 45
        },
        integrationTest: {
            coverage: 65.0,
            passRate: 95.5
        },
        defect: {
            open: 5,
            closed: 120,
            avgCloseTime: 2.3
        }
    }
};

export const emptyDashboardData: DashboardData = {
    overallScore: null,
    radarData: [],
    metrics: {
        requirements: { coverage: null, health: null },
        codeQuality: { bugs: null, vulnerabilities: null, debt: null },
        unitTest: { coverage: null, passRate: null, duration: null },
        integrationTest: { coverage: null, passRate: null },
        defect: { open: null, closed: null, avgCloseTime: null }
    }
};

export const getDashboardData = (projectId: string, simulateTimeout = false): Promise<DashboardData> => {
    return new Promise((resolve) => {
        const timeout = simulateTimeout ? 6000 : 800; // 模拟正常 800ms，超时 6000ms (>5000ms threshold)
        setTimeout(() => {
            resolve(mockDashboardData);
        }, timeout);
    });
};
