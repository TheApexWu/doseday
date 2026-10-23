"""web/index.html run under node with a stub DOM: the page's own script runs, so its STOP and voice paths are
tested as shipped. Each case is one page load and one user action."""
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "web" / "index.html"

HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const html = fs.readFileSync(input.page, "utf8");
const script = html.slice(html.indexOf("<script>") + 8, html.lastIndexOf("</script>"));
const spoken = [], fetches = [], unhandled = [], els = {};
process.on("unhandledRejection", e => unhandled.push(String((e && e.message) || e)));
const queue = {"/stop": (input.stop || []).slice(), "/cmd": (input.cmd || []).slice()};
const days = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
const statusJson = {busy: null, queued: 0, results: [], days, lids: Object.fromEntries(days.map(d => [d, "open"]))};
function el(id) {
  if (!els[id]) {
    els[id] = {id, textContent: "", innerHTML: "", className: "", hidden: false, disabled: false, dataset: {},
      classList: {add() {}, remove() {}}, appendChild() {}, querySelectorAll: () => []};
  }
  return els[id];
}
function reply(code, body) { return {ok: code >= 200 && code < 300, status: code, json: async () => body}; }
const ctx = {};
ctx.window = ctx;
ctx.document = {getElementById: el, createElement: () => el("(new)")};
ctx.speechSynthesis = {cancel() {}, speak(u) { spoken.push(u.text); }};
ctx.SpeechSynthesisUtterance = function (text) { this.text = text; };
ctx.SpeechRecognition = function () { ctx.recognizer = this; };
ctx.setTimeout = () => 0;
ctx.fetch = async (path, opts) => {
  const o = opts || {};
  fetches.push({path, method: o.method || "GET", body: o.body ? JSON.parse(o.body) : null});
  if (path === "/status") return reply(200, statusJson);
  const next = queue[path] && queue[path].shift();
  if (next && next.reject) throw new Error("connection reset");
  if (next) return reply(next.status, next.body);
  return reply(200, path === "/stop" ? {ok: true, say: "stopped"} : {id: 1});
};
vm.createContext(ctx);
vm.runInContext(script, ctx);
async function flush() { for (let i = 0; i < 50; i++) await new Promise(r => setImmediate(r)); }
(async () => {
  const out = {};
  if (input.op === "parse") out.parse = ctx.parse(input.text);
  if (input.op === "stop_button") el("stop").onclick();
  if (input.op === "utter") ctx.recognizer.onresult({results: [[{transcript: input.text}]]});
  await flush();
  out.spoken = spoken;
  out.fetches = fetches.filter(f => f.path !== "/status");
  out.alarm = el("alarm").textContent;
  out.unhandled = unhandled;
  process.stdout.write(JSON.stringify(out));
})();
"""


def page(**op) -> dict:
    assert shutil.which("node"), "node is required to run the page's script in the page tests"
    proc = subprocess.run(["node", "-e", HARNESS], input=json.dumps({"page": str(PAGE), **op}),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def posts(out, path):
    return [f for f in out["fetches"] if f["path"] == path]


def test_stop_button_says_stopped_only_when_the_server_says_ok():
    out = page(op="stop_button", stop=[{"status": 200, "body": {"ok": True, "say": "stopped"}}])
    assert "Stopping" in out["spoken"]  # positive control: the harness hears the page's speech
    assert "Stopped" in out["spoken"] and out["alarm"] == ""


def test_voice_stop_takes_the_same_path_as_the_button():
    out = page(op="utter", text="stop", stop=[{"status": 200, "body": {"ok": True, "say": "stopped"}}])
    assert len(posts(out, "/stop")) == 1 and "Stopped" in out["spoken"]


def test_a_failed_stop_is_retried_and_shown_not_spoken_as_done():
    failed = {"status": 500, "body": {"ok": False, "say": "STOP failed. The arm may still be moving."}}
    out = page(op="stop_button", stop=[failed, failed, failed])
    assert "Stopping" in out["spoken"]  # positive control
    assert len(posts(out, "/stop")) == 3
    assert "Stopped" not in out["spoken"] and "may still be moving" in out["alarm"]


def test_a_dropped_stop_connection_counts_as_a_failed_stop():
    out = page(op="stop_button", stop=[{"reject": True}] * 3)
    assert "Stopped" not in out["spoken"] and "may still be moving" in out["alarm"]
    assert out["unhandled"] == []
