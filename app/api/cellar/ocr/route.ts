import { NextRequest, NextResponse } from "next/server";
import Anthropic from "@anthropic-ai/sdk";

export async function POST(req: NextRequest) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ error: "ocr_unavailable" }, { status: 503 });
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

  // Convert to base64
  const arrayBuffer = await imageFile.arrayBuffer();
  const base64 = Buffer.from(arrayBuffer).toString("base64");
  const mediaType = (imageFile.type || "image/jpeg") as
    | "image/jpeg"
    | "image/png"
    | "image/gif"
    | "image/webp";

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
