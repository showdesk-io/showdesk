/**
 * Zero-dependency dev server for the widget.
 *
 * Serves built JS from dist/ and the demo page from the project root.
 * Used alongside `rollup -c -w` in the Docker dev container.
 */

import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join, extname } from "node:path";

const MIME = {
  ".js": "application/javascript",
  ".html": "text/html",
  ".map": "application/json",
  ".css": "text/css",
};

const PORT = 3001;

createServer(async (req, res) => {
  const url = req.url.split("?")[0];
  const file = url === "/" ? "/widget.js" : url;

  // Try dist/ first (built JS + sourcemaps), then project root (demo page)
  let data = null;
  for (const base of ["dist", "."]) {
    try {
      data = await readFile(join(base, file));
      break;
    } catch {
      /* try next */
    }
  }

  if (data) {
    res.writeHead(200, {
      "Content-Type": MIME[extname(file)] || "application/octet-stream",
      "Access-Control-Allow-Origin": "*",
      "Cache-Control": "no-cache",
    });
    res.end(data);
  } else {
    res.writeHead(404, { "Content-Type": "text/plain" });
    res.end("Not found");
  }
}).listen(PORT, "0.0.0.0", () => {
  console.log(`[widget] dev server http://0.0.0.0:${PORT}`);
});
