/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./agent-output/**/*.{html,css}",
    "./agent/src/webppt_agent/templates/**/*.{py,html}",
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
