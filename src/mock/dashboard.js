export const mockDashboardData = {
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
export const emptyDashboardData = {
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
export const getDashboardData = (projectId, simulateTimeout = false) => {
    return new Promise((resolve) => {
        const timeout = simulateTimeout ? 6000 : 800; // 模拟正常 800ms，超时 6000ms (>5000ms threshold)
        setTimeout(() => {
            resolve(mockDashboardData);
        }, timeout);
    });
};
