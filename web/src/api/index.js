// VITE_USE_MOCK=1이면 목 API, 아니면 실제 서버(/api 프록시)
import { createClient } from './client.js';
import { createMockClient } from './mock/mock.js';
import { navigate } from '../lib/router.js';

export const USE_MOCK = import.meta.env.VITE_USE_MOCK === '1';
export const api = USE_MOCK ? createMockClient() : createClient({ onUnauthorized: () => navigate('/company') });
