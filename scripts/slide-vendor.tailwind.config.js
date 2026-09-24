/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./agent-output/**/*.{html,css}",
    "./backend/templates/**/*.{py,html}",
  ],
  // 幻灯片页自带重置；避免与 theme.css 冲突的 preflight
  corePlugins: {
    preflight: false,
  },
  theme: {
    extend: {},
  },
  plugins: [],
};
