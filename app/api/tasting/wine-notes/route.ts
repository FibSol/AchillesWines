import { NextRequest, NextResponse } from "next/server";
import Anthropic from "@anthropic-ai/sdk";
import { z } from "zod";
import { and, eq, inArray } from "drizzle-orm";
import { db } from "@/db";
import { aiWineNotes } from "@/db/schema";

export const dynamic = "force-dynamic";

const MODEL = "claude-sonnet-5";

const LANGUAGE_NAMES: Record<string, string> = {
  fr: "French",
  en: "English",
  nl: "Dutch",
  de: "German",
  es: "Spanish",
  it: "Italian",
};

const WineIn = z.object({
  wineKey: z.string().min(1),
  producerName: z.string(),
  cuveeName: z.string(),
  vintage: z.number().int().nullable(),
  color: z.string(),
  appellationName: z.string(),
  region: z.string(),
  grapes: z.array(z.string()).default([]),
});

const PostBody = z.object({
  locale: z.enum(["fr", "en", "nl", "de", "es", "it"]),
  wines: z.array(WineIn).min(1).max(12),
});

interface WineNote {
  description: string;
  funFact: string;
}

const GeneratedNote = z.object({
  wineKey: z.string(),
  description: z.string().min(1),
  funFact: z.string().min(1),
});

/**
 * Returns an AI-written blurb (short description + anecdote/fun fact) per
 * wine, in the requested locale. Cached in ai_wine_notes — the Anthropic API
 * is only called for (wine, locale) pairs not yet in the cache.
 */
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  const parsed = PostBody.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues.map((i) => i.message).join(", ") },
      { status: 400 },
    );
  }
  const { locale, wines } = parsed.data;

  // 1. Serve everything we already have from the cache.
  const cached = await db
    .select()
    .from(aiWineNotes)
    .where(
      and(
        inArray(
          aiWineNotes.wineKey,
          wines.map((w) => w.wineKey),
        ),
        eq(aiWineNotes.locale, locale),
      ),
    );
  const notes: Record<string, WineNote> = {};
  for (const row of cached) {
    notes[row.wineKey] = { description: row.description, funFact: row.funFact };
  }

  const missing = wines.filter((w) => !notes[w.wineKey]);
  if (missing.length === 0) {
    return NextResponse.json({ notes, generated: 0, cached: cached.length });
  }

  if (!process.env.ANTHROPIC_API_KEY) {
    // Still useful: return whatever the cache had.
    return NextResponse.json({ notes, generated: 0, cached: cached.length, aiUnavailable: true });
  }

  // 2. One API call for all missing wines.
  const client = new Anthropic();
  const wineList = missing.map((w) => ({
    wineKey: w.wineKey,
    producer: w.producerName,
    cuvee: w.cuveeName,
    vintage: w.vintage,
    color: w.color,
    appellation: w.appellationName,
    region: w.region,
    grapes: w.grapes,
  }));

  let responseText: string;
  try {
    const message = await client.messages.create({
      model: MODEL,
      // Generous budget: the model may spend part of it on internal reasoning
      // blocks before the JSON text block, and truncated JSON is unusable.
      max_tokens: Math.min(600 * missing.length + 2000, 8000),
      system:
        "You are a knowledgeable sommelier and wine writer. You write short, engaging blurbs for a tasting sheet. You are rigorous about facts: never invent specific claims (dates, awards, ratings, family stories). If you are not confident about a specific producer, write about the appellation, terroir or grape variety instead — those facts must be real and well-known.",
      messages: [
        {
          role: "user",
          content: `Write in ${LANGUAGE_NAMES[locale]}. For each wine below, write:
1. "description" — 2–3 sentences on the wine's typical style, terroir and character. No scores, no prices.
2. "funFact" — one genuinely interesting anecdote or fun fact. Prefer the producer/estate if you are confident about it; otherwise the appellation, region or grape variety. It must not repeat the description.

Return ONLY a JSON array, one object per wine, exactly:
[{"wineKey": "...", "description": "...", "funFact": "..."}]

Wines (${missing.length}):
${JSON.stringify(wineList, null, 1)}`,
        },
      ],
    });
    // The response may lead with non-text blocks (e.g. thinking) — take the text one.
    const block = message.content.find((b) => b.type === "text");
    if (!block || block.type !== "text") {
      return NextResponse.json({ error: "unexpected_response" }, { status: 502 });
    }
    responseText = block.text;
  } catch (err) {
    console.error("[wine-notes] Anthropic API error:", err);
    return NextResponse.json({ error: "ai_api_error", notes }, { status: 502 });
  }

  // 3. Parse, cache, merge.
  const cleaned = responseText
    .trim()
    .replace(/^```(?:json)?\s*/i, "")
    .replace(/\s*```$/, "")
    .trim();
  let generated: unknown;
  try {
    generated = JSON.parse(cleaned);
  } catch {
    return NextResponse.json({ error: "parse_failure", notes }, { status: 502 });
  }
  const arr = z.array(GeneratedNote).safeParse(generated);
  if (!arr.success) {
    return NextResponse.json({ error: "parse_failure", notes }, { status: 502 });
  }

  const validKeys = new Set(missing.map((w) => w.wineKey));
  let inserted = 0;
  for (const note of arr.data) {
    if (!validKeys.has(note.wineKey)) continue; // ignore hallucinated keys
    try {
      await db
        .insert(aiWineNotes)
        .values({
          wineKey: note.wineKey,
          locale,
          description: note.description,
          funFact: note.funFact,
          model: MODEL,
        })
        .onConflictDoUpdate({
          target: [aiWineNotes.wineKey, aiWineNotes.locale],
          set: { description: note.description, funFact: note.funFact, model: MODEL },
        });
      inserted++;
    } catch {
      // FK violation (wineKey not in dim_wine): still return the note, just uncached.
    }
    notes[note.wineKey] = { description: note.description, funFact: note.funFact };
  }

  return NextResponse.json({ notes, generated: inserted, cached: cached.length });
}
