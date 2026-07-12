export const API_KEY_STORAGE_KEY = "hubster_api_key";

export function getStoredApiKey(): string | null {
  try {
    return sessionStorage.getItem(API_KEY_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setStoredApiKey(apiKey: string): void {
  try {
    sessionStorage.setItem(API_KEY_STORAGE_KEY, apiKey);
  } catch {
    // Unavailable storage (e.g. Safari private mode) — treat as a failed write.
  }
}

export function clearStoredApiKey(): void {
  try {
    sessionStorage.removeItem(API_KEY_STORAGE_KEY);
  } catch {
    // Unavailable storage — clearing is best-effort, same as a missing key.
  }
}

export function hasStoredApiKey(): boolean {
  const key = getStoredApiKey();
  return key !== null && key.length > 0;
}
