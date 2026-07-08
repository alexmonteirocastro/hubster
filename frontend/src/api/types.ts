export type CountryCode = "DK" | "SE" | "NO" | "FI" | "IS" | "EU";

export interface ChatRequest {
  question: string;
  limit?: number;
  country?: CountryCode | null;
  remote?: boolean | null;
}

export interface ChatSource {
  score: number;
  job_id: string;
  job_url: string;
  job_role: string;
  document_text: string;
  job_title?: string | null;
  company?: string | null;
  country?: string | null;
  location?: string | null;
}

export interface ChatResponse {
  question: string;
  answer: string;
  sources: ChatSource[];
  generated: boolean;
  applied_country?: CountryCode | null;
  applied_remote?: boolean | null;
}
