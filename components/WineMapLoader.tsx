"use client";

import dynamic from "next/dynamic";
import type { ProducerPin, AppellationOverlay } from "./WineMap";

const WineMapDynamic = dynamic(
  () => import("./WineMap").then((m) => m.WineMap),
  {
    ssr: false,
    loading: () => (
      <div
        className="glass-card animate-pulse"
        style={{ height: "620px" }}
      />
    ),
  }
);

type Props = {
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

export function WineMapLoader(props: Props) {
  return <WineMapDynamic {...props} />;
}
