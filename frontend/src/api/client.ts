import type { ResumeData } from '../types/resume';

const BASE = '/api';

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const err = await res.json();
      message = err.detail || JSON.stringify(err);
    } catch {
      // ignore JSON parse errors
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

export async function parseResume(file: File): Promise<{ text: string }> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${BASE}/parse-resume`, { method: 'POST', body: form });
  return handleResponse<{ text: string }>(res);
}

export async function scrapeJd(url: string): Promise<{ text: string }> {
  const res = await fetch(`${BASE}/scrape-jd`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
  return handleResponse<{ text: string }>(res);
}

export async function generateResume(
  resume_text: string,
  jd_text: string
): Promise<ResumeData> {
  const res = await fetch(`${BASE}/generate-resume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resume_text, jd_text }),
  });
  return handleResponse<ResumeData>(res);
}

export async function downloadPdf(resume: ResumeData): Promise<Blob> {
  const res = await fetch(`${BASE}/download-pdf`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(resume),
  });
  if (!res.ok) {
    let message = `PDF generation failed (${res.status})`;
    try {
      const err = await res.json();
      message = err.detail || JSON.stringify(err);
    } catch {
      // ignore
    }
    throw new Error(message);
  }
  return res.blob();
}
