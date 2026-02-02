import type { Config } from "tailwindcss"

export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
    "./packages/dashboard/src/**/*.{js,ts,jsx,tsx}",
  ],
} satisfies Config

