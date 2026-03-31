import resolve from "@rollup/plugin-node-resolve";
import typescript from "@rollup/plugin-typescript";
import terser from "@rollup/plugin-terser";

const isProduction = process.env.BUILD === "production";

function createPlugins() {
  return [
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
  ].filter(Boolean);
}

export default [
  // IIFE build — for <script> tag / CDN usage
  {
    input: "src/widget.ts",
    output: {
      file: "dist/widget.js",
      format: "iife",
      name: "Showdesk",
      sourcemap: !isProduction,
    },
    plugins: createPlugins(),
  },
  // ESM build — for npm / bundler usage
  {
    input: "src/widget.ts",
    output: {
      file: "dist/widget.esm.js",
      format: "esm",
      sourcemap: !isProduction,
    },
    plugins: createPlugins(),
  },
];
