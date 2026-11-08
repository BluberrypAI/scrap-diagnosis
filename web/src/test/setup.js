import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => {
  cleanup();
  localStorage.clear();
  window.location.hash = '';
});

// jsdom에 없는 API
if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = function () {};
if (!window.matchMedia) {
  window.matchMedia = (q) => ({
    matches: false,
    media: q,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
  });
}
