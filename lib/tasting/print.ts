/**
 * Printable tasting-sheet builder. Pure: takes a flight + cellar temperature,
 * returns a self-contained HTML document (light theme, A4) with a preparation
 * plan (chill / decant lead times) and the serving order.
 *
 * Chilling rates from a cellar-temperature bottle (75 cl):
 *   - refrigerator (~4 °C): ≈ 10 min per °C to drop
 *   - ice + water bucket:   ≈ 2.5 min per °C to drop
 * e.g. 19 °C → 7 °C (sparkling): ~2 h fridge, ~30 min ice bucket.
 */

import type { TastingFlight, FlightStop, DirectiveNote } from "@/lib/tasting/engine";

type Translator = (key: string, values?: Record<string, string | number>) => string;

export interface ChillPlan {
  /** °C to drop from cellar temp to the middle of the serving range (0 = ready). */
  deltaC: number;
  fridgeMinutes: number;
  iceBathMinutes: number;
}

function roundTo5(min: number): number {
  return Math.max(5, Math.round(min / 5) * 5);
}

export function chillPlan(serveTempC: [number, number], cellarTempC: number): ChillPlan {
  const target = (serveTempC[0] + serveTempC[1]) / 2;
  const delta = cellarTempC - target;
  if (delta <= 1) return { deltaC: 0, fridgeMinutes: 0, iceBathMinutes: 0 };
  return {
    deltaC: delta,
    fridgeMinutes: roundTo5(delta * 10),
    iceBathMinutes: roundTo5(delta * 2.5),
  };
}

function esc(s: string): string {
  return s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function stopDisplayName(stop: FlightStop): string {
  const vintage = stop.vintage !== null ? ` ${stop.vintage}` : "";
  return `${stop.producerName} — ${stop.cuveeName}${vintage}`;
}

interface PrepAction {
  minutesBefore: number;
  label: string;
  wine: string;
}

export interface PrintSheetInput {
  flight: TastingFlight;
  cellarTempC: number;
  locale: string;
  /** Translator scoped to the "tasting" namespace. */
  t: Translator;
  renderNote: (note: DirectiveNote) => string;
}

export function buildPrintHtml({ flight, cellarTempC, locale, t, renderNote }: PrintSheetInput): string {
  const modeName = t(`modes.${flight.mode}.name`);
  const axis = flight.selectedAxis ? ` · ${flight.selectedAxis.label}` : "";
  const date = new Date().toLocaleDateString(locale, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  // ---- Preparation plan: one action per chill / decant, longest lead first ----
  const actions: PrepAction[] = [];
  for (const stop of flight.stops) {
    const chill = chillPlan(stop.serveTempC, cellarTempC);
    const wine = `${stop.position}. ${stopDisplayName(stop)}`;
    if (chill.fridgeMinutes > 0) {
      actions.push({
        // Chilling happens on the closed bottle, so it must finish before the
        // wine is opened / decanted — shift its start back by the decant time.
        minutesBefore: chill.fridgeMinutes + stop.decantMinutes,
        label:
          t("print.actionFridge", {
            temp: cellarTempC,
            low: stop.serveTempC[0],
            high: stop.serveTempC[1],
          }) +
          " " +
          t("print.actionIceAlt", { minutes: chill.iceBathMinutes }),
        wine,
      });
    }
    if (stop.decantMinutes > 0) {
      actions.push({
        minutesBefore: stop.decantMinutes,
        label: t("print.actionDecant"),
        wine,
      });
    }
  }
  actions.sort((a, b) => b.minutesBefore - a.minutesBefore);

  const prepRows =
    actions.length > 0
      ? actions
          .map(
            (a) => `<tr>
              <td class="time">${esc(t("print.hMinus", { minutes: a.minutesBefore }))}</td>
              <td><strong>${esc(a.wine)}</strong><br/><span class="muted">${esc(a.label)}</span></td>
            </tr>`,
          )
          .join("")
      : `<tr><td colspan="2" class="muted">${esc(t("print.nothingToPrep"))}</td></tr>`;

  // ---- Serving order ----
  const stopBlocks = flight.stops
    .map((stop) => {
      const chill = chillPlan(stop.serveTempC, cellarTempC);
      const facts: string[] = [
        t("print.serveAt", { low: stop.serveTempC[0], high: stop.serveTempC[1] }),
        t(`glass.${stop.glassType}`),
      ];
      if (chill.fridgeMinutes > 0) {
        facts.push(t("print.chillFridge", { minutes: chill.fridgeMinutes }));
        facts.push(t("print.chillIce", { minutes: chill.iceBathMinutes }));
      } else {
        facts.push(t("print.readyFromCellar"));
      }
      if (stop.decantMinutes > 0) {
        facts.push(t("print.decant", { minutes: stop.decantMinutes }));
      }
      const meta = [stop.appellationName, stop.region, stop.grapes.join(", ")]
        .filter(Boolean)
        .join(" · ");
      const notes = stop.notes.map((n) => `<li>${esc(renderNote(n))}</li>`).join("");
      return `<div class="stop">
        <div class="stop-head">
          <span class="pos">${stop.position}</span>
          <div>
            <p class="name">${esc(stopDisplayName(stop))}</p>
            <p class="meta">${esc(meta)}</p>
          </div>
        </div>
        <p class="facts">${facts.map(esc).join(" &nbsp;·&nbsp; ")}</p>
        ${notes ? `<ul class="notes">${notes}</ul>` : ""}
      </div>`;
    })
    .join("");

  const directives = flight.overall.map((n) => `<li>${esc(renderNote(n))}</li>`).join("");

  return `<!doctype html>
<html lang="${esc(locale)}">
<head>
<meta charset="utf-8"/>
<title>${esc(t("print.sheetTitle"))} — ${esc(modeName)}</title>
<style>
  @page { margin: 14mm; }
  * { box-sizing: border-box; }
  body { font: 10.5pt/1.5 Georgia, "Times New Roman", serif; color: #1c1a1e; margin: 0 auto; max-width: 180mm; padding: 8mm; }
  header { border-bottom: 2px solid #a53860; padding-bottom: 4mm; margin-bottom: 5mm; }
  h1 { font-size: 15pt; margin: 0; letter-spacing: 0.03em; }
  h1 small { color: #a53860; font-weight: normal; }
  .subline { margin: 1mm 0 0; color: #555; font-size: 9.5pt; }
  h2 { font-size: 11.5pt; color: #a53860; margin: 6mm 0 2mm; text-transform: uppercase; letter-spacing: 0.06em; }
  .hint { margin: 0 0 2mm; color: #777; font-size: 8.5pt; font-style: italic; }
  table { width: 100%; border-collapse: collapse; }
  td { padding: 1.6mm 2mm; border-bottom: 1px solid #ddd; vertical-align: top; }
  td.time { white-space: nowrap; font-weight: bold; width: 26mm; font-variant-numeric: tabular-nums; }
  .muted { color: #666; font-size: 9pt; }
  ul { margin: 0; padding-left: 5mm; }
  li { margin-bottom: 1mm; }
  .stop { border: 1px solid #ccc; border-radius: 2mm; padding: 3mm 4mm; margin-bottom: 3mm; page-break-inside: avoid; }
  .stop-head { display: flex; gap: 3mm; align-items: baseline; }
  .pos { font-size: 14pt; font-weight: bold; color: #a53860; min-width: 6mm; }
  .name { font-weight: bold; margin: 0; }
  .meta { margin: 0.5mm 0 0; color: #666; font-size: 9pt; }
  .facts { margin: 1.5mm 0 1mm; font-size: 9pt; color: #333; border-top: 1px dotted #ccc; padding-top: 1.5mm; }
  .notes { font-size: 8.5pt; color: #555; }
  footer { margin-top: 6mm; color: #999; font-size: 8pt; text-align: center; }
</style>
</head>
<body>
<header>
  <h1>Achilles's Wines <small>· ${esc(t("print.sheetTitle"))}</small></h1>
  <p class="subline">${esc(modeName)}${esc(axis)} — ${esc(t("print.printedOn", { date }))} · ${esc(t("print.cellarAt", { temp: cellarTempC }))}</p>
</header>

<h2>${esc(t("print.prepTitle"))}</h2>
<p class="hint">${esc(t("print.prepSubtitle"))}</p>
<table>${prepRows}</table>

<h2>${esc(t("ui.directives"))}</h2>
<ul>${directives}</ul>

<h2>${esc(t("print.serviceTitle"))}</h2>
${stopBlocks}

<footer>Achilles's Wines</footer>
<script>addEventListener("load", () => setTimeout(() => print(), 200));</script>
</body>
</html>`;
}
