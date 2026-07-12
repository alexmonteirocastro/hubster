export const API_KEY_STORAGE_KEY = "hubster_api_key";

export function getStoredApiKey(): string | null {
  try {
    return sessionStorage.getItem(API_KEY_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setStoredApiKey(apiKey: string): void {
  sessionStorage.setItem(API_KEY_STORAGE_KEY, apiKey);
}

export function clearStoredApiKey(): void {
  sessionStorage.removeItem(API_KEY_STORAGE_KEY);
}

export function hasStoredApiKey(): boolean {
  const key = getStoredApiKey();
  return key !== null && key.length > 0;
}
