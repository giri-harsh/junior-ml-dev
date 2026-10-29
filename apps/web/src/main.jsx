import React, { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

const api = async (path, opts = {}) => {
  const r = await fetch(path, { credentials: "same-origin", ...opts });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`${r.status} ${JSON.stringify(body.detail ?? body)}`);
  return body;
};
const post = (path, data) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data ?? {}) });

function Login({ onDone }) {
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await post("/v1/auth/login", { user, password });
          onDone();
        } catch (x) {
          setErr(String(x));
        }
      }}
    >
      <h2>Sign in</h2>
      <label>User <input value={user} onChange={(e) => setUser(e.target.value)} autoComplete="username" /></label>
      <label>Password <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
      <button type="submit">Sign in</button>
      {err && <p role="alert" className="err">{err}</p>}
    </form>
  );
}

function RunDetail({ runId, onBack }) {
  const [run, setRun] = useState(null);
  const [msg, setMsg] = useState("");
  const load = useCallback(() => api(`/v1/runs/${encodeURIComponent(runId)}`).then(setRun).catch((e) => setMsg(String(e))), [runId]);
  useEffect(() => { load(); }, [load]);
  if (!run) return <p>{msg || "Loading…"}</p>;
  const res = run.result || {};
  const pending = res.pending_approval;
  return (
    <section>
      <button onClick={onBack}>← Runs</button>
      <h2>{run.run_id}</h2>
      <p>Status: <strong>{run.status}</strong> · planner {res.planner ?? "?"} · LLM mode {res.llm_mode ?? "?"}</p>
      <ul>
        <li>Chosen family: {res.chosen_family ?? "n/a"} · validation score: {res.val_score ?? "n/a"}</li>
        <li>Reviewer: {res.review ?? "n/a"} · steps: {res.n_steps ?? "?"} · latency: {res.latency_s ?? "?"} s</li>
      </ul>
      {res.report && (
        <p><a href={`/v1/runs/${encodeURIComponent(runId)}/report`} target="_blank" rel="noopener noreferrer">Open report</a></p>
      )}
      {pending && (
        <p>
          Deploy is waiting for approval.{" "}
          <button
            onClick={async () => {
              try {
                const t = await post(`/v1/approvals/${encodeURIComponent(pending.approval_id)}/approve`);
                await post(`/v1/runs/${encodeURIComponent(runId)}/resume`, { approval_token: t.token });
                setMsg("Approved; the run will resume."); load();
              } catch (e) { setMsg(String(e)); }
            }}
          >Approve deploy (single use)</button>
        </p>
      )}
      {msg && <p role="status">{msg}</p>}
    </section>
  );
}

function App() {
  const [authed, setAuthed] = useState(false);
  const [runs, setRuns] = useState([]);
  const [sel, setSel] = useState(null);
  const [err, setErr] = useState("");
  const refresh = useCallback(() => {
    api("/v1/runs").then((r) => { setRuns(r); setAuthed(true); setErr(""); }).catch((e) => { setAuthed(false); setErr(String(e)); });
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  if (!authed) return <main><h1>junior-ml-dev</h1><Login onDone={refresh} />{err && <p className="note">{err}</p>}</main>;
  if (sel) return <main><RunDetail runId={sel} onBack={() => { setSel(null); refresh(); }} /></main>;
  return (
    <main>
      <h1>Runs</h1>
      <button onClick={refresh}>Refresh</button>
      <table>
        <thead><tr><th>Run</th><th>Status</th><th>Updated</th></tr></thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.run_id}>
              <td><button className="link" onClick={() => setSel(r.run_id)}>{r.run_id}</button></td>
              <td>{r.status}</td>
              <td>{new Date(r.updated * 1000).toLocaleString()}</td>
            </tr>
          ))}
          {runs.length === 0 && <tr><td colSpan="3">No runs yet. Start one from /ui.</td></tr>}
        </tbody>
      </table>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
