// Starts the two pages the tests drive, on synthetic data only, and stops them afterwards.
//
// - static: `frontdesk export-demo <tmp>` (the public demo, Slack threads included) served by a
//   tiny Node static server on 127.0.0.1. Set FD_E2E_APP_JS=<file> to serve that file as app.js
//   instead (how a red proof runs a broken copy without touching the repo).
// - live: tests/e2e/live_server.py, the real server in demo mode on a throwaway store, for Ask.
//
// Python: FRONTDESK_PYTHON, else the repo's .venv, else python3. FRONTDESK_HOME always points at
// a temp dir, so nothing here reads ~/.frontdesk.
import { spawn, spawnSync } from "node:child_process";
import { createReadStream, existsSync, copyFileSync, mkdtempSync, rmSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { createInterface } from "node:readline";

const ROOT = path.resolve(__dirname, "../..");
const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
};

// The repo's .venv, or the main checkout's when running from a git worktree (worktrees have no
// .venv of their own), else python3. FrontDesk needs Python 3.12+, so an older interpreter is a
// loud failure here rather than an ImportError deep in export-demo.
function python(): string {
  const candidates = [process.env.FRONTDESK_PYTHON, path.join(ROOT, ".venv/bin/python")];
  const common = spawnSync("git", ["rev-parse", "--git-common-dir"], { cwd: ROOT, encoding: "utf-8" });
  if (common.status === 0) candidates.push(path.join(path.resolve(ROOT, common.stdout.trim()), "..", ".venv/bin/python"));
  candidates.push("python3");
  const py = candidates.find(c => c && (c === "python3" || existsSync(c)))!;
  const v = spawnSync(py, ["-c", "import sys; print(sys.version_info >= (3, 12))"], { encoding: "utf-8" });
  if (v.stdout.trim() !== "True") throw new Error(`FrontDesk needs Python 3.12+; ${py} is older. Set FRONTDESK_PYTHON.`);
  return py;
}

export default async function globalSetup() {
  const work = mkdtempSync(path.join(tmpdir(), "fd-e2e-"));
  const site = path.join(work, "site");
  const env = { ...process.env, FRONTDESK_HOME: path.join(work, "home"), PYTHONPATH: ROOT };
  const ex = spawnSync(python(), ["-m", "frontdesk", "export-demo", site],
                       { cwd: ROOT, env, encoding: "utf-8" });
  if (ex.status !== 0) throw new Error("export-demo failed: " + ex.stderr + ex.stdout);
  if (process.env.FD_E2E_APP_JS) copyFileSync(process.env.FD_E2E_APP_JS, path.join(site, "app.js"));

  const stat = createServer((req, res) => {
    const rel = decodeURIComponent((req.url || "/").split("?")[0]).replace(/^\/+/, "") || "index.html";
    const file = path.resolve(site, rel);
    if (!file.startsWith(site + path.sep) || !existsSync(file) || !statSync(file).isFile()) {
      res.writeHead(404).end("Not found\n");
      return;
    }
    res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream",
                         "Cache-Control": "no-store" });
    createReadStream(file).pipe(res);
  });
  await new Promise<void>(ok => stat.listen(0, "127.0.0.1", ok));
  const port = (stat.address() as { port: number }).port;
  process.env.FD_STATIC_URL = `http://127.0.0.1:${port}/index.html`;

  const live = spawn(python(), [path.join(__dirname, "live_server.py")],
                     { cwd: ROOT, env, stdio: ["pipe", "pipe", "inherit"] });
  const line = await new Promise<string>((ok, fail) => {
    const t = setTimeout(() => fail(new Error("live server did not start in 30s")), 30000);
    createInterface({ input: live.stdout! }).once("line", l => { clearTimeout(t); ok(l); });
    live.once("exit", code => { clearTimeout(t); fail(new Error("live server exited " + code)); });
  });
  process.env.FD_LIVE_URL = JSON.parse(line).live;

  return async () => {
    live.stdin!.end();
    await new Promise(ok => { live.once("exit", ok); setTimeout(ok, 5000); });
    await new Promise(ok => stat.close(ok));
    rmSync(work, { recursive: true, force: true });
  };
}
