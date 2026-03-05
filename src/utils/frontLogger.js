const KEY = 'uni-portal-front-logs';
const readLogs = () => {
    try {
        const raw = localStorage.getItem(KEY);
        return raw ? JSON.parse(raw) : [];
    }
    catch {
        return [];
    }
};
export const pushFrontLog = (entry) => {
    const next = [{ ...entry, time: new Date().toISOString() }, ...readLogs()].slice(0, 200);
    localStorage.setItem(KEY, JSON.stringify(next));
};
