// tailwind.config.js - design tokens for the NOC console (colors + fonts)
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0E1726",      // page background (dark: NOC wall screens)
        panel: "#16233A",    // cards / panels
        line: "#24344F",     // borders
        txt: "#DCE6F2",      // main text
        mute: "#8597B0",     // secondary text
        sig: "#4CC3E8",      // signal / interactive accent
        crit: "#F0525B",     // critical
        major: "#F59E0B",    // major
        ok: "#34D399",       // healthy
      },
      fontFamily: {
        sans: ["'IBM Plex Sans'", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
