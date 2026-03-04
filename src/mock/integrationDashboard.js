export const mockIntegrationData = {
    testCaseDimensions: [
        { name: '功能', value: 120 },
        { name: '性能', value: 80 },
        { name: '边界', value: 60 },
        { name: '接口', value: 90 },
        { name: '兼容', value: 50 },
        { name: '稳定性', value: 70 },
        { name: '可用性', value: 85 },
        { name: '安全性', value: 40 }
    ],
    softwareExecution: {
        total: 1000,
        completed: 850,
        passed: 800,
        passRate: 94.1
    },
    hardwareExecution: {
        total: 500,
        completed: 480,
        passed: 470,
        passRate: 97.9
    },
    stats: {
        testFiles: 45,
        totalCases: 1500,
        currentFailed: 15,
        fixedFailed: 120,
        currentInvalid: 8,
        fixedInvalid: 5
    },
    trendData: [
        { date: '2023-10-01', failed: 5, passed: 100 },
        { date: '2023-10-02', failed: 8, passed: 150 },
        { date: '2023-10-03', failed: 12, passed: 220 },
        { date: '2023-10-04', failed: 10, passed: 300 },
        { date: '2023-10-05', failed: 6, passed: 450 },
        { date: '2023-10-06', failed: 4, passed: 580 },
        { date: '2023-10-07', failed: 2, passed: 700 }
    ]
};
export const emptyIntegrationData = {
    testCaseDimensions: [],
    softwareExecution: { total: 0, completed: 0, passed: 0, passRate: 0 },
    hardwareExecution: { total: 0, completed: 0, passed: 0, passRate: 0 },
    stats: {
        testFiles: 0,
        totalCases: 0,
        currentFailed: 0,
        fixedFailed: 0,
        currentInvalid: 0,
        fixedInvalid: 0
    },
    trendData: []
};
export const getIntegrationDashboardData = (projectId, simulateTimeout = false) => {
    return new Promise((resolve) => {
        const timeout = simulateTimeout ? 6000 : 800;
        setTimeout(() => {
            resolve(mockIntegrationData);
        }, timeout);
    });
};
