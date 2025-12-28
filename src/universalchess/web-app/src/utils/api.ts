/**
 * API URL management for PWA.
 * 
 * The API URL is stored in localStorage and defaults to the configured API target
 * when first installed. This allows the PWA to remember which chess board
 * it was installed from, while also allowing users to change it.
 */

// Injected by Vite at build time - the actual API target URL
declare const __API_TARGET__: string;

const API_URL_KEY = 'universal-chess-api-url';

/**
 * Get the default API URL.
 * In development, this is the Vite proxy target (e.g., http://dgt.local).
 * In production, this is the origin the app was served from.
 */
export function getDefaultApiUrl(): string {
  // Use the build-time configured API target if available
  if (typeof __API_TARGET__ !== 'undefined' && __API_TARGET__) {
    return __API_TARGET__;
  }
  // Fallback to current origin (production PWA)
  return window.location.origin;
}

/**
 * Get the stored API URL, or the default if not set.
 * On first access (PWA install), stores the default API URL.
 * 
 * If the stored value is localhost but we have a configured API target,
 * we update to use the configured target (handles dev mode correctly).
 */
export function getApiUrl(): string {
  const stored = localStorage.getItem(API_URL_KEY);
  const defaultUrl = getDefaultApiUrl();
  
  if (stored) {
    // If stored is localhost but we have a real API target configured,
    // update to use the configured target
    const isStoredLocalhost = stored.includes('localhost') || stored.includes('127.0.0.1');
    const isDefaultNotLocalhost = !defaultUrl.includes('localhost') && !defaultUrl.includes('127.0.0.1');
    
    if (isStoredLocalhost && isDefaultNotLocalhost) {
      // User likely ran in dev mode first, now has proper config
      localStorage.setItem(API_URL_KEY, defaultUrl);
      return defaultUrl;
    }
    
    return stored;
  }
  
  // First time - save the default API URL
  localStorage.setItem(API_URL_KEY, defaultUrl);
  return defaultUrl;
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
 * Reset API URL to default (configured API target or current origin).
 */
export function resetApiUrl(): void {
  localStorage.setItem(API_URL_KEY, getDefaultApiUrl());
}

/**
 * Check if we're in development mode (running on localhost with Vite proxy).
 */
export function isDevMode(): boolean {
  const hostname = window.location.hostname;
  return hostname === 'localhost' || hostname === '127.0.0.1';
}

/**
 * Build a full URL for an API endpoint.
 * In development mode, returns the path as-is for Vite proxy.
 * In production PWA with a different origin, returns the full URL.
 */
export function buildApiUrl(path: string): string {
  // In dev mode, always use relative paths to go through Vite proxy
  if (isDevMode()) {
    return path;
  }
  
  const apiUrl = getApiUrl();
  const currentOrigin = window.location.origin;
  
  // If API URL is the same as current origin, use relative paths
  if (apiUrl === currentOrigin) {
    return path;
  }
  
  // Different origin - build full URL
  return `${apiUrl}${path}`;
}

/**
 * Check if we're using a cross-origin API.
 * In dev mode, we use the proxy so it's not cross-origin.
 */
export function isCrossOriginApi(): boolean {
  if (isDevMode()) {
    return false;
  }
  return getApiUrl() !== window.location.origin;
}

const AUTH_CREDENTIALS_KEY = 'universal-chess-auth';
const AUTH_SESSION_KEY = 'universal-chess-auth-session';

/**
 * Get stored Basic Auth credentials.
 * Returns base64-encoded "username:password" or null if not stored.
 * Checks localStorage first (persistent), then sessionStorage (temporary).
 */
export function getStoredCredentials(): string | null {
  return localStorage.getItem(AUTH_CREDENTIALS_KEY) || sessionStorage.getItem(AUTH_SESSION_KEY);
}

/**
 * Store Basic Auth credentials.
 * Credentials should be base64-encoded "username:password".
 * 
 * @param base64Credentials - The encoded credentials
 * @param persistent - If true, store in localStorage (survives browser close).
 *                     If false, store in sessionStorage (cleared when tab closes).
 */
export function storeCredentials(base64Credentials: string, persistent: boolean = true): void {
  if (persistent) {
    localStorage.setItem(AUTH_CREDENTIALS_KEY, base64Credentials);
    // Clear session storage if we're persisting
    sessionStorage.removeItem(AUTH_SESSION_KEY);
  } else {
    sessionStorage.setItem(AUTH_SESSION_KEY, base64Credentials);
    // Don't clear localStorage - if user had persistent creds, keep them
  }
}

/**
 * Clear stored credentials from both storage types.
 */
export function clearCredentials(): void {
  localStorage.removeItem(AUTH_CREDENTIALS_KEY);
  sessionStorage.removeItem(AUTH_SESSION_KEY);
}

/**
 * Encode username and password for Basic Auth.
 */
export function encodeBasicAuth(username: string, password: string): string {
  return btoa(`${username}:${password}`);
}

/**
 * Fetch wrapper that automatically uses the correct API URL.
 * Handles cross-origin requests and authentication appropriately.
 * 
 * For authenticated requests, set `requiresAuth: true` in the options.
 * Credentials are stored in localStorage and sent via Authorization header.
 */
export async function apiFetch(
  path: string, 
  init?: RequestInit & { requiresAuth?: boolean }
): Promise<Response> {
  const url = buildApiUrl(path);
  const { requiresAuth, ...fetchInit } = init || {};
  const options: RequestInit = { ...fetchInit };
  
  // Add CORS mode for cross-origin requests
  if (isCrossOriginApi()) {
    options.mode = 'cors';
    options.credentials = 'include';
  }
  
  // Add stored credentials for authenticated requests
  if (requiresAuth) {
    const credentials = getStoredCredentials();
    if (credentials) {
      options.headers = {
        ...options.headers,
        'Authorization': `Basic ${credentials}`,
      };
    }
  }
  
  return fetch(url, options);
}

