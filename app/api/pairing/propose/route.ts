import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db";
import {
  dimWine,
  dimProducer,
  dimAppellation,
  cellarInventory,
  factPrice,
  factRating,
} from "@/db/schema";
import { eq, sql, inArray } from "drizzle-orm";
import { z } from "zod";
import { scorePairing, type CourseType, type WineColor } from "@/lib/pairing";

const CourseSchema = z.object({
  id: z.string(),
  type: z.enum(["aperitif", "entree", "plat", "fromage", "dessert", "other"]),
  dish: z.string().max(200),
});

const PostBody = z.object({
  courses: z.array(CourseSchema).min(1).max(8),
  guests: z.number().int().min(1).max(50).default(2),
  budgetEur: z.number().min(0).optional(),
  preferCellar: z.boolean().default(true),
});

interface WineCandidate {
  wineKey: string;
  canonicalName: string;
  producerName: string;
  cuveeName: string;
  vintage: number | null;
  color: WineColor;
  appellationName: string;
  avgRating: number | null;
  avgPriceEur: number | null;
  inventoryQty: number;
  sourceCount: number;
}

interface CourseSuggestion {
  courseId: string;
  picks: Array<{
    candidate: WineCandidate;
    score: number;
    breakdown: ReturnType<typeof scorePairing>;
    rationale: string[];
  }>;
}

function rationaleFor(
  course: CourseType,
  dish: string,
  candidate: WineCandidate,
  breakdown: ReturnType<typeof scorePairing>,
): string[] {
  const out: string[] = [];
  if (breakdown.colorMatch >= 100) out.push(`strong ${candidate.color} match for ${course}`);
  else if (breakdown.colorMatch >= 60) out.push(`${candidate.color} fits ${course}`);
  if (candidate.inventoryQty > 0) out.push(`${candidate.inventoryQty} in cellar`);
  if (candidate.avgRating !== null && candidate.avgRating >= 90) out.push(`critic ${candidate.avgRating.toFixed(0)}/100`);
  if (breakdown.budgetPenalty < 0) out.push(`over budget`);
  if (out.length === 0) out.push(`fallback pick (limited cellar data)`);
  void dish;
  return out;
}

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  const parsed = PostBody.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues.map((i) => i.message).join(", ") },
      { status: 400 },
    );
  }
  const { courses, guests, budgetEur, preferCellar } = parsed.data;

  // Load candidate pool: prefer cellar wines, fall back to dim_wine when cellar empty / not enough.
  const cellarRows = await db
    .select({
      wineKey: dimWine.wineKey,
      canonicalName: dimWine.canonicalName,
      cuveeName: dimWine.cuveeName,
      vintage: dimWine.vintage,
      color: dimWine.color,
      producerName: dimProducer.producerName,
      appellationName: dimAppellation.appellationName,
      qty: sql<number>`coalesce(sum(${cellarInventory.qty}), 0)`,
      purchasePriceEur: sql<number | null>`avg(${cellarInventory.purchasePriceEur})`,
    })
    .from(cellarInventory)
    .innerJoin(dimWine, eq(cellarInventory.wineKey, dimWine.wineKey))
    .innerJoin(dimProducer, eq(dimWine.producerKey, dimProducer.producerKey))
    .innerJoin(dimAppellation, eq(dimWine.appellationKey, dimAppellation.appellationKey))
    .groupBy(dimWine.wineKey);

  const wineKeysFromCellar = new Set(cellarRows.map((r) => r.wineKey));

  // If too few cellar wines, top up with dim_wine
  let registryRows: typeof cellarRows = [];
  if (!preferCellar || cellarRows.length < 12) {
    const limit = preferCellar ? 200 : 500;
    const allRows = await db
      .select({
        wineKey: dimWine.wineKey,
        canonicalName: dimWine.canonicalName,
        cuveeName: dimWine.cuveeName,
        vintage: dimWine.vintage,
        color: dimWine.color,
        producerName: dimProducer.producerName,
        appellationName: dimAppellation.appellationName,
        qty: sql<number>`0`,
        purchasePriceEur: sql<number | null>`null`,
      })
      .from(dimWine)
      .innerJoin(dimProducer, eq(dimWine.producerKey, dimProducer.producerKey))
      .innerJoin(dimAppellation, eq(dimWine.appellationKey, dimAppellation.appellationKey))
      .limit(limit);
    registryRows = allRows.filter((r) => !wineKeysFromCellar.has(r.wineKey));
  }

  const pool = [...cellarRows, ...registryRows];
  if (pool.length === 0) {
    return NextResponse.json({
      suggestions: courses.map((c) => ({ courseId: c.id, picks: [] })),
      poolSize: 0,
    });
  }

  const poolKeys = pool.map((p) => p.wineKey);

  // Aggregates per wine — prices + ratings + source count
  const [priceAgg, ratingAgg] = await Promise.all([
    db
      .select({
        wineKey: factPrice.wineKey,
        avgPrice: sql<number>`avg(${factPrice.amountEur})`,
        sourceKey: factPrice.sourceKey,
      })
      .from(factPrice)
      .where(inArray(factPrice.wineKey, poolKeys))
      .groupBy(factPrice.wineKey, factPrice.sourceKey),
    db
      .select({
        wineKey: factRating.wineKey,
        avgRating: sql<number>`avg(${factRating.scoreNormalized100})`,
        sourceKey: factRating.sourceKey,
      })
      .from(factRating)
      .where(inArray(factRating.wineKey, poolKeys))
      .groupBy(factRating.wineKey, factRating.sourceKey),
  ]);

  const priceByWine = new Map<string, { sum: number; count: number; sources: Set<number> }>();
  for (const row of priceAgg) {
    const r = priceByWine.get(row.wineKey) ?? { sum: 0, count: 0, sources: new Set() };
    if (row.avgPrice !== null && row.avgPrice > 0) {
      r.sum += Number(row.avgPrice);
      r.count++;
    }
    r.sources.add(row.sourceKey);
    priceByWine.set(row.wineKey, r);
  }
  const ratingByWine = new Map<string, { sum: number; count: number; sources: Set<number> }>();
  for (const row of ratingAgg) {
    const r = ratingByWine.get(row.wineKey) ?? { sum: 0, count: 0, sources: new Set() };
    if (row.avgRating !== null) {
      r.sum += Number(row.avgRating);
      r.count++;
    }
    r.sources.add(row.sourceKey);
    ratingByWine.set(row.wineKey, r);
  }

  const candidates: WineCandidate[] = pool.map((r) => {
    const pStats = priceByWine.get(r.wineKey);
    const rStats = ratingByWine.get(r.wineKey);
    const sources = new Set<number>([
      ...(pStats?.sources ?? new Set<number>()),
      ...(rStats?.sources ?? new Set<number>()),
    ]);
    return {
      wineKey: r.wineKey,
      canonicalName: r.canonicalName,
      producerName: r.producerName,
      cuveeName: r.cuveeName,
      vintage: r.vintage,
      color: r.color as WineColor,
      appellationName: r.appellationName,
      avgRating: rStats && rStats.count > 0 ? rStats.sum / rStats.count : null,
      avgPriceEur: pStats && pStats.count > 0
        ? pStats.sum / pStats.count
        : (r.purchasePriceEur ? Number(r.purchasePriceEur) : null),
      inventoryQty: Number(r.qty ?? 0),
      sourceCount: sources.size,
    };
  });

  const budgetPerGuest =
    budgetEur && budgetEur > 0 ? budgetEur / Math.max(1, guests) / Math.max(1, courses.length) : null;

  const suggestions: CourseSuggestion[] = courses.map((course) => {
    const scored = candidates
      .map((c) => {
        const breakdown = scorePairing({
          course: course.type as CourseType,
          dishText: course.dish,
          wineColor: c.color,
          ratingNorm100: c.avgRating,
          inventoryQty: c.inventoryQty,
          pricePerGuestEur: c.avgPriceEur,
          budgetPerGuestEur: budgetPerGuest,
        });
        return {
          candidate: c,
          score: breakdown.total,
          breakdown,
          rationale: rationaleFor(course.type as CourseType, course.dish, c, breakdown),
        };
      })
      .filter((s) => s.breakdown.colorMatch > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 5);

    return { courseId: course.id, picks: scored };
  });

  return NextResponse.json({ suggestions, poolSize: pool.length, budgetPerGuest });
}
