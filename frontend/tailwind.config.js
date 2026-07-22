export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        /* 롯데마트 레드 (고객사 CI 근사값) */
        brand: {
          50: "#FFF0F1", 100: "#FFDDDF", 200: "#FFC1C5",
          400: "#FF4B58", 500: "#F5142A", 600: "#E60012", 700: "#C0000F", 900: "#78000A",
        },
        /* 보조색 — 오렌지(중간 경고 D-1) · 블루(AI·예측 영역) */
        cjorange: { 50: "#FFF4E8", 100: "#FFE4C4", 500: "#F58220", 600: "#D96B00", 700: "#A85200" },
        cjblue: { 50: "#EAF4FC", 100: "#CFE6F8", 500: "#1E88CB", 600: "#0072BC", 700: "#005A96" },
      },
      fontFamily: {
        sans: ["Pretendard", "-apple-system", "BlinkMacSystemFont", "Malgun Gothic", "sans-serif"],
      },
      keyframes: {
        "fade-up": { "0%": { opacity: 0, transform: "translateY(10px)" }, "100%": { opacity: 1, transform: "translateY(0)" } },
        "slide-in": { "0%": { opacity: 0, transform: "translateY(16px) translateX(-50%)" }, "100%": { opacity: 1, transform: "translateY(0) translateX(-50%)" } },
        shimmer: { "100%": { transform: "translateX(100%)" } },
      },
      animation: {
        "fade-up": "fade-up .5s ease-out both",
        "slide-in": "slide-in .35s ease-out both",
      },
    },
  },
  plugins: [],
};
