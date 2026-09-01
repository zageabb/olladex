"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { request } from "../lib/api";

type Run = { id: number; command: string; output: string; exit_code: number; status: "pending" | "running" | "completed" | "cancelled" | "timed_out" | "blocked"; created_at?: string };

export function TerminalPanel({ projectId }: { projectId: number }) {
  const [command, setCommand] = useState("");
  const [runningId, setRunningId] = useState<number | null>(null);
  const [status, setStatus] = useState("Ready");
  const hostRef = useRef<HTMLDivElement>(null);
  const terminalRef = useRef<import("@xterm/xterm").Terminal | null>(null);
  const fitRef = useRef<import("@xterm/addon-fit").FitAddon | null>(null);
  const runningIdRef = useRef<number | null>(null);
  const outputLengthsRef = useRef(new Map<number, number>());
  const pollTimerRef = useRef<number | null>(null);
  const inputTimerRef = useRef<number | null>(null);
  const inputBufferRef = useRef("");
  const projectRef = useRef(projectId);

  function setActive(id: number | null) {
    runningIdRef.current = id;
    setRunningId(id);
  }

  function writeRun(run: Run) {
    const terminal = terminalRef.current;
    if (!terminal) return;
    terminal.write(`\r\n\x1b[1;32m$\x1b[0m ${run.command}\r\n`);
    if (run.output) terminal.write(run.output);
    if (run.status !== "running" && run.status !== "pending") {
      terminal.write(`${run.output.endsWith("\n") ? "" : "\r\n"}\x1b[90m[${run.status} · exit ${run.exit_code}]\x1b[0m\r\n`);
    }
    outputLengthsRef.current.set(run.id, run.output.length);
  }

  useEffect(() => {
    let disposed = false;
    projectRef.current = projectId;
    outputLengthsRef.current.clear();
    setActive(null);
    setStatus("Opening terminal…");

    async function initialise() {
      if (!hostRef.current) return;
      const [{ Terminal }, { FitAddon }] = await Promise.all([import("@xterm/xterm"), import("@xterm/addon-fit")]);
      if (disposed || !hostRef.current) return;
      const terminal = new Terminal({
        allowProposedApi: false,
        convertEol: true,
        cursorBlink: true,
        cursorStyle: "bar",
        fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", monospace',
        fontSize: 11,
        lineHeight: 1.35,
        scrollback: 5000,
        theme: { background: "#0c1728", foreground: "#c8d6e8", cursor: "#57d297", selectionBackground: "#2979ff55", black: "#101c30", brightBlack: "#7085a3", green: "#57d297", brightGreen: "#74e8ae", red: "#ff7b72", brightRed: "#ff9a93", blue: "#63a3ff", brightBlue: "#8abbff" },
      });
      const fit = new FitAddon();
      terminal.loadAddon(fit);
      terminal.open(hostRef.current);
      terminalRef.current = terminal;
      fitRef.current = fit;
      fit.fit();
      terminal.writeln("\x1b[90mOlladex local terminal · bash · selected repository\x1b[0m");
      terminal.onData((data) => queueInput(data));

      const observer = new ResizeObserver(() => {
        try { fit.fit(); } catch { return; }
        const active = runningIdRef.current;
        if (active) request(`/terminal/${active}/resize`, { method: "POST", body: JSON.stringify({ columns: terminal.cols, rows: terminal.rows }) }).catch(() => {});
      });
      observer.observe(hostRef.current);

      try {
        const data = await request<Run[]>(`/projects/${projectId}/terminal`);
        if (disposed || projectRef.current !== projectId) return;
        const ordered = [...data].reverse();
        ordered.forEach(writeRun);
        const active = ordered.find((run) => run.status === "running" || run.status === "pending");
        if (active) {
          setActive(active.id);
          setStatus("Interactive process running");
          terminal.focus();
          poll(active.id);
        } else {
          setStatus("Ready");
        }
      } catch (error) {
        setStatus(error instanceof Error ? error.message : "Unable to load terminal history");
      }

      return () => observer.disconnect();
    }

    let disconnect: (() => void) | undefined;
    initialise().then((cleanup) => { disconnect = cleanup; });
    return () => {
      disposed = true;
      disconnect?.();
      if (pollTimerRef.current) window.clearTimeout(pollTimerRef.current);
      if (inputTimerRef.current) window.clearTimeout(inputTimerRef.current);
      terminalRef.current?.dispose();
      terminalRef.current = null;
      fitRef.current = null;
    };
  }, [projectId]);

  async function execute(event: FormEvent) {
    event.preventDefault();
    if (!command.trim() || runningIdRef.current) return;
    const sent = command.trim();
    setCommand("");
    const terminal = terminalRef.current;
    terminal?.write(`\r\n\x1b[1;32m$\x1b[0m ${sent}\r\n`);
    try {
      const run = await request<Run>(`/projects/${projectId}/terminal/start`, { method: "POST", body: JSON.stringify({ command: sent, columns: terminal?.cols || 120, rows: terminal?.rows || 32 }) });
      outputLengthsRef.current.set(run.id, run.output.length);
      if (run.output) terminal?.write(run.output);
      setActive(run.id);
      setStatus("Interactive process running");
      terminal?.focus();
      poll(run.id);
    } catch (error) {
      terminal?.writeln(`\x1b[31m${error instanceof Error ? error.message : String(error)}\x1b[0m`);
      setStatus("Command failed to start");
    }
  }

  async function poll(id: number) {
    if (projectRef.current !== projectId) return;
    try {
      const current = await request<Run>(`/terminal/${id}`);
      const previousLength = outputLengthsRef.current.get(id) || 0;
      if (current.output.length > previousLength) terminalRef.current?.write(current.output.slice(previousLength));
      outputLengthsRef.current.set(id, current.output.length);
      if (current.status === "running" || current.status === "pending") {
        pollTimerRef.current = window.setTimeout(() => poll(id), 250);
      } else {
        terminalRef.current?.write(`${current.output.endsWith("\n") ? "" : "\r\n"}\x1b[90m[${current.status} · exit ${current.exit_code}]\x1b[0m\r\n`);
        setActive(null);
        setStatus(`${current.status} · exit ${current.exit_code}`);
      }
    } catch (error) {
      setActive(null);
      setStatus(error instanceof Error ? error.message : "Terminal connection lost");
    }
  }

  function queueInput(data: string) {
    if (!runningIdRef.current) return;
    inputBufferRef.current += data;
    if (inputTimerRef.current) return;
    inputTimerRef.current = window.setTimeout(async () => {
      inputTimerRef.current = null;
      const id = runningIdRef.current;
      const queued = inputBufferRef.current;
      inputBufferRef.current = "";
      if (!id || !queued) return;
      try { await request(`/terminal/${id}/input`, { method: "POST", body: JSON.stringify({ data: queued }) }); }
      catch (error) { setStatus(error instanceof Error ? error.message : "Unable to send terminal input"); }
    }, 20);
  }

  async function cancel() {
    const id = runningIdRef.current;
    if (!id) return;
    await request(`/terminal/${id}`, { method: "DELETE" });
    poll(id);
  }

  function sendControl(data: string) {
    queueInput(data);
    terminalRef.current?.focus();
  }

  function clear() {
    terminalRef.current?.clear();
    terminalRef.current?.writeln("\x1b[90mOlladex terminal view cleared\x1b[0m");
    terminalRef.current?.focus();
  }

  return <div className="terminal-panel">
    <div className="xterm-host" ref={hostRef} onClick={() => terminalRef.current?.focus()} />
    <div className="terminal-controls"><span>{status}</span>{runningId && <><button onClick={() => sendControl("\u0003")}>Ctrl-C</button><button onClick={() => sendControl("\t")}>Tab</button><button onClick={() => sendControl("\u001b[A")}>↑</button><button onClick={() => sendControl("\u001b[B")}>↓</button><button onClick={() => sendControl("\u001b")}>Esc</button><button onClick={cancel}>Stop</button></>}<button onClick={clear}>Clear</button></div>
    {!runningId && <form className="terminal-input" onSubmit={execute}><span className="prompt">$</span><input value={command} onChange={(event) => setCommand(event.target.value)} placeholder="Enter a bash command" autoComplete="off" /><button>Run</button></form>}
  </div>;
}
