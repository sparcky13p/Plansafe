// Vercel Blob client-upload token endpoint (Node runtime).
// The browser uploads large plans straight to Blob; this only signs the upload.
// Auth is checked by forwarding the caller's session token to the Python API (/api/me).
import { handleUpload } from "@vercel/blob/client";

const ALLOWED = [
  "application/dxf",
  "image/vnd.dxf",
  "application/pdf",
  "application/octet-stream",
  "text/csv",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "image/jpeg",
  "image/png",
];

export async function POST(request) {
  const body = await request.json();
  try {
    const result = await handleUpload({
      body,
      request,
      // The browser sends its session token as clientPayload (the Blob client
      // cannot add headers to this request).
      onBeforeGenerateToken: async (pathname, clientPayload) => {
        const auth = clientPayload ? `Bearer ${clientPayload}` : request.headers.get("authorization") ?? "";
        const me = await fetch(new URL("/api/me", request.url), { headers: { authorization: auth } });
        if (!me.ok) throw new Error("Sign in required");
        if (!/\.(dxf|pdf|csv|xlsx|jpe?g|png)$/i.test(pathname)) throw new Error("Unsupported file type");
        return { allowedContentTypes: ALLOWED, maximumSizeInBytes: 60 * 1024 * 1024, addRandomSuffix: true };
      },
      onUploadCompleted: async () => {},
    });
    return Response.json(result);
  } catch (err) {
    return Response.json({ error: String(err.message ?? err) }, { status: 400 });
  }
}
