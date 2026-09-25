import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

function backendUrl() {
  return (
    process.env.DASHBOARD_BACKEND_URL ||
    process.env.NEXT_PUBLIC_DASHBOARD_API_URL ||
    "http://127.0.0.1:8000"
  ).replace(/\/$/, "");
}

export async function GET(request: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(request, params.path, "GET");
}
export async function POST(request: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(request, params.path, "POST");
}
export async function PATCH(request: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(request, params.path, "PATCH");
}
export async function DELETE(request: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(request, params.path, "DELETE");
}

async function proxy(request: NextRequest, path: string[], method: string) {
  const key = process.env.DASHBOARD_BACKEND_KEY || process.env.NEXT_PUBLIC_DASHBOARD_API_KEY || "";
  const target = `${backendUrl()}/${path.join("/")}${request.nextUrl.search}`;
  const headers = new Headers();
  headers.set("X-Dashboard-Key", key);
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);

  const body = method === "GET" || method === "DELETE" ? undefined : await request.text();
  try {
    const upstream = await fetch(target, {
      method,
      headers,
      body,
      cache: "no-store",
    });
    const responseBody = await upstream.text();
    return new NextResponse(responseBody, {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") || "application/json" },
    });
  } catch (error) {
    return NextResponse.json(
      { detail: `Dashboard backend unavailable: ${error instanceof Error ? error.message : "unknown error"}` },
      { status: 503 },
    );
  }
}
