// Thin fetch wrapper. When Clerk is configured, AuthGate installs a token getter.

let getToken: (() => Promise<string | null>) | null = null;

export function setTokenGetter(fn: (() => Promise<string | null>) | null) {
  getToken = fn;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function headers(extra: Record<string, string> = {}): Promise<Record<string, string>> {
  const token = getToken ? await getToken() : null;
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

type Opts = { method?: string; json?: unknown; form?: FormData };

export async function api<T>(path: string, opts: Opts = {}): Promise<T> {
  const init: RequestInit = { method: opts.method ?? (opts.json || opts.form ? "POST" : "GET") };
  if (opts.json !== undefined) {
    init.headers = await headers({ "Content-Type": "application/json" });
    init.body = JSON.stringify(opts.json);
  } else {
    init.headers = await headers();
    if (opts.form) init.body = opts.form;
  }
  const r = await fetch(path, init);
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const body = await r.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* not JSON */
    }
    throw new ApiError(r.status, detail);
  }
  return r.status === 204 ? (undefined as T) : r.json();
}

/** Fetch an authenticated binary resource as an object URL (images). */
export async function objectUrl(path: string): Promise<string> {
  const r = await fetch(path, { headers: await headers() });
  if (!r.ok) throw new ApiError(r.status, r.statusText);
  return URL.createObjectURL(await r.blob());
}

/** Download an authenticated file (PDF report, XLSX). */
export async function download(path: string, filename: string) {
  const url = await objectUrl(path);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** Large plans go browser -> Vercel Blob; the API then reads them by URL. */
export async function uploadToBlob(file: File): Promise<string> {
  const { upload } = await import("@vercel/blob/client");
  const token = getToken ? await getToken() : null;
  const blob = await upload(file.name, file, {
    access: "public",
    handleUploadUrl: "/api/blob-upload",
    clientPayload: token ?? "",
  });
  return blob.url;
}

export const DIRECT_UPLOAD_LIMIT = 4 * 1024 * 1024;
