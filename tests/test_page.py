"""web/index.html run under node with a stub DOM: the page's own script runs, so its STOP and typed-answer paths
are tested as shipped. Each case is one page load and one user action. The page has no voice (Alex, 24 Oct)."""
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
const spoken = [], shown = [], fetches = [], unhandled = [], els = {};
process.on("unhandledRejection", e => unhandled.push(String((e && e.message) || e)));
const queue = {"/stop": (input.stop || []).slice(), "/cmd": (input.cmd || []).slice(),
               "/select": (input.select || []).slice()};
const days = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
const statusJson = {busy: null, queued: 0, results: [], days, lids: Object.fromEntries(days.map(d => [d, "open"]))};
function el(id) {
  if (!els[id]) {
    let text = "";
    els[id] = {id, innerHTML: "", className: "", hidden: false, disabled: false, dataset: {},
      classList: {add() {}, remove() {}}, appendChild() {}, querySelectorAll: () => [],
      get textContent() { return text; }, set textContent(v) { text = v; if (id === "heard") shown.push(v); }};
  }
  return els[id];
}
function reply(code, body) { return {ok: code >= 200 && code < 300, status: code, json: async () => body}; }
const ctx = {};
ctx.window = ctx;
ctx.document = {getElementById: el, createElement: () => el("(new)")};
ctx.speechSynthesis = {cancel() {}, speak(u) { spoken.push(u.text); }};
ctx.SpeechSynthesisUtterance = function (text) { this.text = text; };
ctx.SpeechRecognition = function () { ctx.recognizer = this; };  // offered, so a page that wanted voice would take it
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
  if (input.op === "stop_button") el("stop").onclick();
  if (input.op === "type") { el("cmd-text").value = input.text; el("cmd-form").onsubmit({preventDefault() {}}); }
  await flush();
  out.spoken = spoken;
  out.shown = shown;
  out.recognizer = !!ctx.recognizer;
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


def test_the_page_never_speaks_or_listens():
    out = page(op="stop_button", stop=[{"status": 200, "body": {"ok": True, "say": "stopped"}}])
    assert "Stopped" in out["shown"]  # positive control: the action ran
    assert out["spoken"] == [] and out["recognizer"] is False
    html = PAGE.read_text()
    assert "speechSynthesis" not in html and "SpeechRecognition" not in html and 'id="mic"' not in html


def test_stop_button_shows_stopped_only_when_the_server_says_ok():
    out = page(op="stop_button", stop=[{"status": 200, "body": {"ok": True, "say": "stopped"}}])
    assert "Stopping…" in out["shown"]  # positive control: the harness sees the page's text
    assert out["shown"][-1] == "Stopped" and out["alarm"] == ""


def test_a_failed_stop_is_retried_and_shown_not_reported_as_done():
    failed = {"status": 500, "body": {"ok": False, "say": "STOP failed. The arm may still be moving."}}
    out = page(op="stop_button", stop=[failed, failed, failed])
    assert "Stopping…" in out["shown"]  # positive control
    assert len(posts(out, "/stop")) == 3
    assert "Stopped" not in out["shown"] and "may still be moving" in out["alarm"]


def test_a_dropped_stop_connection_counts_as_a_failed_stop():
    out = page(op="stop_button", stop=[{"reject": True}] * 3)
    assert "Stopped" not in out["shown"] and "may still be moving" in out["alarm"]
    assert out["unhandled"] == []


def test_a_typed_answer_goes_to_the_server_with_today():
    out = page(op="type", text="Monday")
    body = posts(out, "/select")[0]["body"]
    assert body["text"] == "Monday" and body["today"] in range(7) and posts(out, "/cmd") == []


def test_a_typed_answer_is_sent_as_typed():
    out = page(op="type", text="white capsule")
    assert posts(out, "/select")[0]["body"]["text"] == "white capsule"


def test_a_stop_word_is_never_ignored_even_beside_a_negation():
    out = page(op="type", text="don't stop, orange tums", stop=[{"status": 200, "body": {"ok": True}}])
    assert len(posts(out, "/stop")) == 1 and posts(out, "/select") == []


def test_typing_stop_stops_the_arm():
    out = page(op="type", text="stop", stop=[{"status": 200, "body": {"ok": True}}])
    assert len(posts(out, "/stop")) == 1 and posts(out, "/select") == []


def test_the_page_shows_the_servers_answer():
    out = page(op="type", text="tuesday or friday",
               select=[{"status": 400, "body": {"ok": False, "say": "I heard more than one day. Say one day."}}])
    assert "I heard more than one day. Say one day." in out["shown"]
