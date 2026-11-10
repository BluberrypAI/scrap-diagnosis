import { USE_MOCK } from '../api/index.js';

// 개발자 화면(AI 데이터 확인·규칙 그래프): 개발 서버에서만. 엔진 API도 prod에서 404
export const DEV_TOOLS = import.meta.env.DEV && !USE_MOCK;
