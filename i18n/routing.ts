import { defineRouting } from "next-intl/routing";

export const routing = defineRouting({
  locales: ["fr", "en", "nl", "de", "es", "it"],
  defaultLocale: "fr",
  localePrefix: "as-needed",
});
