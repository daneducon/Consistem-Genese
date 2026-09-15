/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ["DM Sans", "sans-serif"] },
      colors: {
        surface: "#f8f9fa",
        graphite: "#2e2e30",
        coral: "#df5241",
      },
    },
  },
  plugins: [],
}
