export const tools = [
    {
        key: 'doc-review',
        name: '文档智能审查',
        description: '上传或输入文档信息，自动审查一致性与风险点。',
        targetUrl: 'https://example.com/doc-review',
        fields: [
            { key: 'docUrl', label: '文档地址', type: 'text', placeholder: '请输入文档链接' },
            { key: 'scope', label: '审查范围', type: 'text', placeholder: '例如：安全/质量/规范' },
            { key: 'notes', label: '补充说明', type: 'textarea', placeholder: '可选' }
        ]
    },
    {
        key: 'requirement-semantics',
        name: '需求语义理解',
        description: '解析需求文本，输出结构化语义标签与澄清点。',
        targetUrl: 'https://example.com/requirement-semantics',
        fields: [
            { key: 'requirementText', label: '需求文本', type: 'textarea', placeholder: '请输入需求内容' },
            { key: 'domain', label: '所属领域', type: 'text', placeholder: '例如：交易/运营/测试' }
        ]
    },
    {
        key: 'code-analysis',
        name: '代码智能分析',
        description: '对指定仓库或分支进行静态扫描与质量分析。',
        targetUrl: 'https://example.com/code-analysis',
        fields: [
            { key: 'repoUrl', label: '代码仓库', type: 'text', placeholder: '请输入仓库地址' },
            { key: 'branch', label: '分支', type: 'text', placeholder: '例如：main' },
            { key: 'language', label: '语言', type: 'select', options: ['Java', 'Go', 'Python', 'TypeScript'] }
        ]
    },
    {
        key: 'unit-test',
        name: '智能单元测试',
        description: '自动生成单元测试或补全已有测试用例。',
        targetUrl: 'https://example.com/unit-test',
        fields: [
            { key: 'module', label: '目标模块', type: 'text', placeholder: '请输入模块名称' },
            { key: 'framework', label: '测试框架', type: 'select', options: ['JUnit', 'pytest', 'Jest'] },
            { key: 'coverageTarget', label: '覆盖率目标', type: 'text', placeholder: '例如：80%' }
        ]
    },
    {
        key: 'system-test',
        name: '智能配置项/系统测试',
        description: '基于配置项进行系统级测试与回归验证。',
        targetUrl: 'https://example.com/system-test',
        fields: [
            { key: 'environment', label: '测试环境', type: 'select', options: ['DEV', 'SIT', 'UAT', 'PROD'] },
            { key: 'configSet', label: '配置集合', type: 'text', placeholder: '例如：核心配置组A' },
            { key: 'target', label: '测试目标', type: 'textarea', placeholder: '请输入测试范围' }
        ]
    },
    {
        key: 'code-fix',
        name: '代码缺陷智能修复',
        description: '定位缺陷并生成修复建议或补丁。',
        targetUrl: 'https://example.com/code-fix',
        fields: [
            { key: 'issueId', label: '缺陷编号', type: 'text', placeholder: '请输入缺陷编号' },
            { key: 'repoUrl', label: '代码仓库', type: 'text', placeholder: '请输入仓库地址' },
            { key: 'priority', label: '修复优先级', type: 'select', options: ['高', '中', '低'] }
        ]
    }
];
export const defaultProjects = [
    { id: 'p-001', name: '装备软件项目A', description: '用于基础能力验证与回归测试' },
    { id: 'p-002', name: '平台集成项目B', description: '覆盖多工具联调与质量看板' },
    { id: 'p-003', name: '质量专项项目C', description: '聚焦核心模块缺陷与稳定性提升' }
];
