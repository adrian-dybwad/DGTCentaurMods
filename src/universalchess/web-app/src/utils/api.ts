/**
 * API URL management for PWA.
 * 
 * The API URL is stored in localStorage and defaults to the current origin
 * when first installed. This allows the PWA to remember which chess board
 * it was installed from, while also allowing users to change it.
 */

const API_URL_KEY = 'universal-chess-api-url';

/**
 * Get the stored API URL, or the current origin if not set.
 * On first access (PWA install), stores the current origin.
 */
export function getApiUrl(): string {
  const stored = localStorage.getItem(API_URL_KEY);
  
  if (stored) {
    return stored;
  }
  
  // First time - save the current origin
  // In dev mode (localhost:3000), this will be the dev server
  // In production PWA, this will be the actual chess board URL (e.g., http://dgt.local)
  const origin = window.location.origin;
  localStorage.setItem(API_URL_KEY, origin);
  return origin;
}

/**
 * Set a new API URL.
 */
export function setApiUrl(url: string): void {
  // Normalize the URL - remove trailing slash
  const normalized = url.replace(/\/+$/, '');
  localStorage.setItem(API_URL_KEY, normalized);
}

/**
 * Check if a custom API URL has been set (different from current origin).
 */
export function hasCustomApiUrl(): boolean {
  const stored = localStorage.getItem(API_URL_KEY);
  return stored !== null && stored !== window.location.origin;
}

/**
 * Reset API URL to current origin.
 */
export function resetApiUrl(): void {
  localStorage.setItem(API_URL_KEY, window.location.origin);
}

/**
 * Build a full URL for an API endpoint.
 * In development (same origin), returns the path as-is for Vite proxy.
 * In production PWA with a different origin, returns the full URL.
 */
export function buildApiUrl(path: string): string {
  const apiUrl = getApiUrl();
  const currentOrigin = window.location.origin;
  
  // If API URL is the same as current origin, use relative paths
  // This works with Vite proxy in development
  if (apiUrl === currentOrigin) {
    return path;
  }
  
  // Different origin - build full URL
  return `${apiUrl}${path}`;
}

/**
 * Check if we're using a cross-origin API.
 */
export function isCrossOriginApi(): boolean {
  return getApiUrl() !== window.location.origin;
}

/**
 * Fetch wrapper that automatically uses the correct API URL.
 * Handles cross-origin requests appropriately.
 */
export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const url = buildApiUrl(path);
  const options: RequestInit = { ...init };
  
  // Add CORS mode for cross-origin requests
  if (isCrossOriginApi()) {
    options.mode = 'cors';
  }
  
  return fetch(url, options);
}

