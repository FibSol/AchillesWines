"use client";

import { MapContainer, TileLayer, CircleMarker, Popup, GeoJSON } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import type { GeoJsonObject } from "geojson";

export type ProducerPin = {
  producerKey: number;
  producerName: string;
  region: string | null;
  subregion: string | null;
  latitude: number;
  longitude: number;
  tier: number | null;
};

export type AppellationOverlay = {
  appellationKey: number;
  appellationName: string;
  region: string;
  level: string;
  geoPolygon: string | null;
  latitude: number | null;
  longitude: number | null;
};

type WineMapProps = {
  producers: ProducerPin[];
  appellations: AppellationOverlay[];
  locale: string;
  labels: {
    noData: string;
    legendProducers: string;
    legendAppellations: string;
    legendRegions: string;
  };
};

const CORAL = "#A53860";
const CORAL_FILL = "rgba(165,56,96,0.18)";
const MINT = "#5EA87A";
const MINT_FILL = "rgba(94,168,122,0.7)";

const TIER_COLORS: Record<number, string> = {
  1: "#E5B25D", // gold   — iconic / top domaines
  2: "#A53860", // coral  — premier tier
  3: "#5EA87A", // mint   — solid producers
  4: "#C99440", // amber  — standard
  5: "#3a3750", // muted violet — entry level
};
const TIER_COLOR_NULL = "#5A5270"; // no tier assigned

function tierColor(tier: number | null): string {
  if (tier == null) return TIER_COLOR_NULL;
  return TIER_COLORS[tier] ?? TIER_COLOR_NULL;
}

export function WineMap({ producers, appellations, locale, labels }: WineMapProps) {
  const withPolygon = appellations.filter((a) => a.geoPolygon);
  const withPin = appellations.filter((a) => !a.geoPolygon && a.latitude != null && a.longitude != null);
  const hasAnyData = producers.length > 0 || withPolygon.length > 0 || withPin.length > 0;

  if (!hasAnyData) {
    return (
      <div
        className="glass-card flex items-center justify-center text-[color:var(--color-fg-muted)] text-sm"
        style={{ height: "620px" }}
      >
        {labels.noData}
      </div>
    );
  }

  return (
    <div className="relative rounded-xl overflow-hidden" style={{ height: "620px" }}>
      <MapContainer
        center={[46.8, 2.3]}
        zoom={6}
        style={{ height: "100%", width: "100%" }}
        className="z-0"
      >
        <TileLayer
          attribution='&copy; <a href="https://carto.com/attributions">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        />

        {/* GeoJSON region overlays */}
        {withPolygon.map((a) => {
          let data: GeoJsonObject;
          try {
            data = JSON.parse(a.geoPolygon!) as GeoJsonObject;
          } catch {
            return null;
          }
          return (
            <GeoJSON
              key={`geo-${a.appellationKey}`}
              data={data}
              style={() => ({
                color: CORAL,
                weight: 1.5,
                fillColor: CORAL_FILL,
                fillOpacity: 1,
                opacity: 0.7,
              })}
            >
              <Popup>
                <div style={{ fontFamily: "sans-serif", fontSize: "13px" }}>
                  <a
                    href={`/${locale}/appellations/${a.appellationKey}`}
                    style={{ color: "#A53860", fontWeight: "bold", textDecoration: "underline", cursor: "pointer" }}
                  >
                    {a.appellationName}
                  </a>
                  <br />
                  <span style={{ color: "#888" }}>{a.region}</span>
                  <br />
                  <span style={{ fontSize: "11px", color: "#aaa" }}>{a.level}</span>
                </div>
              </Popup>
            </GeoJSON>
          );
        })}

        {/* Appellation centroid pins (where no polygon) */}
        {withPin.map((a) => (
          <CircleMarker
            key={`app-${a.appellationKey}`}
            center={[a.latitude!, a.longitude!]}
            radius={4}
            pathOptions={{
              color: MINT,
              fillColor: MINT_FILL,
              fillOpacity: 1,
              weight: 1.5,
            }}
          >
            <Popup>
              <div style={{ fontFamily: "sans-serif", fontSize: "13px" }}>
                <a
                  href={`/${locale}/appellations/${a.appellationKey}`}
                  style={{ color: "#A53860", fontWeight: "bold", textDecoration: "underline", cursor: "pointer" }}
                >
                  {a.appellationName}
                </a>
                <br />
                <span style={{ color: "#888" }}>{a.region}</span>
                <br />
                <span style={{ fontSize: "11px", color: "#aaa" }}>{a.level}</span>
              </div>
            </Popup>
          </CircleMarker>
        ))}

        {/* Producer markers — colored by tier */}
        {producers.map((p) => {
          const color = tierColor(p.tier);
          return (
            <CircleMarker
              key={`prod-${p.producerKey}`}
              center={[p.latitude, p.longitude]}
              radius={4}
              pathOptions={{
                color,
                fillColor: color,
                fillOpacity: 0.85,
                weight: 1,
              }}
            >
              <Popup>
                <div style={{ fontFamily: "sans-serif", fontSize: "13px" }}>
                  <a
                    href={`/${locale}/domaines/${p.producerKey}`}
                    style={{ color: "#A53860", fontWeight: "bold", textDecoration: "underline", cursor: "pointer" }}
                  >
                    {p.producerName}
                  </a>
                  <br />
                  <span style={{ color: "#888" }}>
                    {p.region}
                    {p.subregion ? ` · ${p.subregion}` : ""}
                  </span>
                  {p.tier != null && (
                    <>
                      <br />
                      <span style={{ fontSize: "11px", color: "#aaa" }}>Tier {p.tier}</span>
                    </>
                  )}
                </div>
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>

      {/* Legend */}
      <div
        className="absolute bottom-4 left-4 z-[1000] glass-card px-3 py-2 space-y-1.5 text-xs"
        style={{ pointerEvents: "none" }}
      >
        {producers.length > 0 && (
          <>
            <p className="text-[color:var(--color-fg-subtle)] uppercase tracking-wider text-[10px] font-mono mb-0.5">
              {labels.legendProducers}
            </p>
            {([1, 2, 3, 4, 5] as const).map((t) => {
              const count = producers.filter((p) => p.tier === t).length;
              if (count === 0) return null;
              return (
                <div key={t} className="flex items-center gap-2">
                  <span
                    className="inline-block size-2.5 rounded-full shrink-0"
                    style={{ background: TIER_COLORS[t] }}
                  />
                  <span className="text-[color:var(--color-fg-muted)]">
                    T{t} · {count}
                  </span>
                </div>
              );
            })}
            {(() => {
              const count = producers.filter((p) => p.tier == null).length;
              return count > 0 ? (
                <div className="flex items-center gap-2">
                  <span
                    className="inline-block size-2.5 rounded-full shrink-0"
                    style={{ background: TIER_COLOR_NULL }}
                  />
                  <span className="text-[color:var(--color-fg-muted)]">— · {count}</span>
                </div>
              ) : null;
            })()}
          </>
        )}
        {withPin.length > 0 && (
          <div className="flex items-center gap-2">
            <span
              className="inline-block size-3 rounded-full shrink-0"
              style={{ background: MINT }}
            />
            <span className="text-[color:var(--color-fg-muted)]">
              {labels.legendAppellations} ({withPin.length})
            </span>
          </div>
        )}
        {withPolygon.length > 0 && (
          <div className="flex items-center gap-2">
            <span
              className="inline-block size-3 rounded shrink-0 border"
              style={{ background: CORAL_FILL, borderColor: CORAL }}
            />
            <span className="text-[color:var(--color-fg-muted)]">
              {labels.legendRegions} ({withPolygon.length})
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
