import { NextRequest, NextResponse } from "next/server";
import Anthropic from "@anthropic-ai/sdk";

// ─── In-memory rate limiter ───────────────────────────────────────────────────
// Caps Anthropic spend on this unauthenticated-friendly endpoint. Single-instance
// (resets on restart), which is fine for the RPi/HA add-on. Behind HA ingress all
// callers share the proxy IP, so the global cap is the real guard.
const RL_WINDOW_MS = 60 * 60 * 1000; // 1 hour
const RL_MAX_GLOBAL = 40;
const RL_MAX_PER_IP = 20;
const rlHits: { t: number; ip: string }[] = [];

function isRateLimited(ip: string): boolean {
  const cutoff = Date.now() - RL_WINDOW_MS;
  while (rlHits.length && rlHits[0].t < cutoff) rlHits.shift();
  if (rlHits.length >= RL_MAX_GLOBAL) return true;
  if (rlHits.filter((h) => h.ip === ip).length >= RL_MAX_PER_IP) return true;
  rlHits.push({ t: Date.now(), ip });
  return false;
}

const ALLOWED_MEDIA = ["image/jpeg", "image/png", "image/gif", "image/webp"] as const;
type AllowedMedia = (typeof ALLOWED_MEDIA)[number];

export async function POST(req: NextRequest) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ error: "ocr_unavailable" }, { status: 503 });
  }

  const ip = (req.headers.get("x-forwarded-for") ?? "").split(",")[0]?.trim() || "local";
  if (isRateLimited(ip)) {
    return NextResponse.json({ error: "rate_limited" }, { status: 429 });
  }

  let formData: FormData;
  try {
    formData = await req.formData();
  } catch {
    return NextResponse.json({ error: "invalid_form_data" }, { status: 400 });
  }

  const imageFile = formData.get("image");
  if (!imageFile || !(imageFile instanceof File)) {
    return NextResponse.json({ error: "missing_image" }, { status: 400 });
  }

  // 5 MB guard
  if (imageFile.size > 5 * 1024 * 1024) {
    return NextResponse.json({ error: "image_too_large" }, { status: 413 });
  }

  // Validate media type against an allowlist (reject anything non-image).
  const declared = (imageFile.type || "image/jpeg").toLowerCase();
  if (!ALLOWED_MEDIA.includes(declared as AllowedMedia)) {
    return NextResponse.json({ error: "unsupported_media_type" }, { status: 415 });
  }
  const mediaType = declared as AllowedMedia;

  // Convert to base64
  const arrayBuffer = await imageFile.arrayBuffer();
  const base64 = Buffer.from(arrayBuffer).toString("base64");

  const client = new Anthropic();

  let responseText: string;
  try {
    const message = await client.messages.create({
      model: "claude-haiku-4-5-20251001",
      max_tokens: 256,
      system:
        "You are a wine label OCR assistant. Extract structured data from wine label images.",
      messages: [
        {
          role: "user",
          content: [
            {
              type: "image",
              source: {
                type: "base64",
                media_type: mediaType,
                data: base64,
              },
            },
            {
              type: "text",
              text: 'Extract from this wine label: producer name, cuvée name (wine name/cuvée), vintage year (4-digit, or null if NV), and appellation. Return ONLY valid JSON: {"producer":"...","cuvee":"...","vintage":2019,"appellation":"...","confidence":"high"|"medium"|"low"}. Use null for fields you cannot read.',
            },
          ],
        },
      ],
    });

    const block = message.content[0];
    if (block.type !== "text") {
      return NextResponse.json({ error: "unexpected_response" }, { status: 502 });
    }
    responseText = block.text;
  } catch (err) {
    console.error("[OCR] Anthropic API error:", err);
    return NextResponse.json({ error: "ocr_api_error" }, { status: 502 });
  }

  // Strip markdown fences if present
  const cleaned = responseText
    .trim()
    .replace(/^```(?:json)?\s*/i, "")
    .replace(/\s*```$/, "")
    .trim();

  type OcrResult = {
    producer: string | null;
    cuvee: string | null;
    vintage: number | null;
    appellation: string | null;
    confidence: "high" | "medium" | "low";
  };

  let parsed: OcrResult;
  try {
    parsed = JSON.parse(cleaned) as OcrResult;
  } catch {
    return NextResponse.json({ error: "parse_failure", raw: cleaned }, { status: 422 });
  }

  return NextResponse.json({
    producer: parsed.producer ?? null,
    cuvee: parsed.cuvee ?? null,
    vintage: parsed.vintage ?? null,
    appellation: parsed.appellation ?? null,
    confidence: parsed.confidence ?? "low",
  });
}
