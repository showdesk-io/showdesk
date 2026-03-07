import resolve from "@rollup/plugin-node-resolve";
import typescript from "@rollup/plugin-typescript";
import terser from "@rollup/plugin-terser";

const isProduction = process.env.BUILD === "production";

export default {
  input: "src/widget.ts",
  output: {
    file: "dist/widget.js",
    format: "iife",
    name: "Showdesk",
    sourcemap: !isProduction,
  },
  plugins: [
    resolve(),
    typescript({
      tsconfig: "./tsconfig.json",
      declaration: false,
      declarationDir: undefined,
    }),
    isProduction && terser({
      format: {
        comments: false,
      },
    }),
  ].filter(Boolean),
};
