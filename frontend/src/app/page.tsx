"use client";

import {
  ArrowDownToLine,
  ArrowUpRight,
  Braces,
  CircleStop,
  Columns2,
  Expand,
  LoaderCircle,
  Monitor,
  Moon,
  Play,
  RefreshCw,
  Smartphone,
  Sun,
  Terminal,
  X,
} from "lucide-react";
import Link from "next/link";
import Script from "next/script";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { Button } from "@/components/ui/button";
import {
  call,
  type Activity,
  type Comparison,
  type Integration,
  type Model,
  type Run,
  type Side,
} from "@/lib/api";

const siteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;
const api = "/api/comparisons";
const sides = ["a", "b"] as const;
const tabs = [
  "Preview",
  "Agent activity",
  "Terminal output",
  "Source files",
] as const;

declare global {
  interface Window {
    turnstile?: {
      render: (
        element: HTMLElement,
        options: Record<string, unknown>,
      ) => string;
      remove: (id: string) => void;
      reset: (id: string) => void;
    };
  }
}

function ModelSelect({
  side,
  catalog,
  selected,
  select,
  value,
  setValue,
}: {
  side: Side;
  catalog: Model[];
  selected: string;
  select: (id: string) => void;
  value: string;
  setValue: (key: string) => void;
}) {
  const providers = [...new Set(catalog.map((model) => model.provider))];
  const model = catalog.find(
    (item) => item.provider + "/" + item.id === selected,
  );
  return (
    <fieldset className="model-field">
      <legend>
        <span className={"side-mark " + side}>{side.toUpperCase()}</span> Model{" "}
        {side.toUpperCase()}
      </legend>
      <select
        aria-label={"Model " + side.toUpperCase()}
        value={selected}
        required
        onChange={(event) => select(event.target.value)}
      >
        <option value="" disabled>
          Choose a model
        </option>
        {providers.map((provider) => (
          <optgroup
            key={provider}
            label={
              catalog.find((item) => item.provider === provider)?.provider_name
            }
          >
            {catalog
              .filter((item) => item.provider === provider)
              .map((item) => (
                <option
                  key={item.id}
                  value={provider + "/" + item.id}
                  disabled={!item.available}
                >
                  {item.name}
                  {item.free
                    ? " · Free"
                    : item.available
                      ? " · API key"
                      : " · Unavailable"}
                </option>
              ))}
          </optgroup>
        ))}
      </select>
      {model?.requires_key && (
        <label className="key-label">
          Provider API key
          <input
            type="password"
            autoComplete="off"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            required
          />
        </label>
      )}
    </fieldset>
  );
}

function Instruction({
  label,
  disabled,
  submit,
}: {
  label: string;
  disabled?: boolean;
  submit: (text: string) => Promise<void>;
}) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  async function send(event: FormEvent) {
    event.preventDefault();
    if (!text.trim()) return;
    setSending(true);
    try {
      await submit(text);
      setText("");
    } catch {
      /* The workspace displays the error. */
    } finally {
      setSending(false);
    }
  }
  return (
    <form className="instruction" onSubmit={send}>
      <input
        aria-label={label}
        placeholder={label}
        value={text}
        onChange={(event) => setText(event.target.value)}
        maxLength={12000}
      />
      <Button
        type="submit"
        variant="outline"
        disabled={disabled || sending || !text.trim()}
      >
        <Play size={14} /> Continue
      </Button>
    </form>
  );
}

function Panel({
  side,
  run,
  events,
  active,
  action,
  download,
  loadFiles,
}: {
  side: Side;
  run: Run;
  events: Activity[];
  active: boolean;
  action: (suffix: string, text?: string) => Promise<void>;
  download: () => Promise<void>;
  loadFiles: () => Promise<string[]>;
}) {
  const [tab, setTab] = useState<(typeof tabs)[number]>("Preview");
  const [mobile, setMobile] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [files, setFiles] = useState<string[] | null>(null);
  const [stopping, setStopping] = useState(false);
  const screen = useRef<HTMLDivElement>(null);
  const visible = events.filter(
    (event) =>
      event.side === side &&
      (tab === "Terminal output"
        ? event.kind === "terminal"
        : event.kind !== "terminal"),
  );
  const ready = ["stopped", "ready", "failed"].includes(run.status);
  return (
    <section
      className={"panel " + (active ? "active-panel" : "")}
      aria-label={"Application " + side.toUpperCase()}
    >
      <header className="panel-heading">
        <span className={"side-mark " + side}>{side.toUpperCase()}</span>
        <div className="model-title">
          <strong>{run.model}</strong>
          <small>{run.provider}</small>
        </div>
        <span className={"status " + run.status}>{run.status}</span>
        <Button
          type="button"
          variant="ghost"
          aria-label={"Stop agent " + side.toUpperCase()}
          title="Stop agent"
          disabled={run.status !== "running" || stopping}
          onClick={async () => {
            setStopping(true);
            try {
              await action("stop");
            } catch {
              /* Reported above. */
            } finally {
              setStopping(false);
            }
          }}
        >
          <CircleStop size={17} />
        </Button>
        <Button
          type="button"
          variant="ghost"
          aria-label={"Export project " + side.toUpperCase()}
          title="Export project"
          disabled={run.status === "created" || run.status === "provisioning"}
          onClick={() => void download()}
        >
          <ArrowDownToLine size={17} />
        </Button>
      </header>
      <nav
        className="panel-tabs"
        aria-label={"Application " + side.toUpperCase() + " views"}
      >
        {tabs.map((item) => (
          <button
            type="button"
            key={item}
            aria-pressed={tab === item}
            onClick={() => {
              setTab(item);
              if (item === "Source files")
                void loadFiles()
                  .then(setFiles)
                  .catch(() => setFiles(null));
            }}
          >
            {item}
          </button>
        ))}
      </nav>
      <div className="preview-area" ref={screen} hidden={tab !== "Preview"}>
        <div className="preview-tools">
          <div className="viewport-tools">
            <Button
              type="button"
              variant="ghost"
              aria-label="Desktop viewport"
              aria-pressed={!mobile}
              onClick={() => setMobile(false)}
            >
              <Monitor size={16} />
            </Button>
            <Button
              type="button"
              variant="ghost"
              aria-label="Mobile viewport"
              aria-pressed={mobile}
              onClick={() => setMobile(true)}
            >
              <Smartphone size={16} />
            </Button>
          </div>
          <div className="viewport-tools">
            <Button
              type="button"
              variant="ghost"
              aria-label="Refresh preview"
              disabled={!run.preview_url}
              onClick={() => setRefresh((value) => value + 1)}
            >
              <RefreshCw size={16} />
            </Button>
            <Button
              type="button"
              variant="ghost"
              aria-label="Fullscreen preview"
              disabled={!run.preview_url}
              onClick={() => {
                const mode = document.fullscreenElement
                  ? document.exitFullscreen()
                  : screen.current?.requestFullscreen();
                void mode?.catch(() => {});
              }}
            >
              <Expand size={16} />
            </Button>
            {run.preview_url && (
              <Button asChild variant="ghost">
                <a
                  href={run.preview_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="Open preview in a new tab"
                >
                  <ArrowUpRight size={16} />
                </a>
              </Button>
            )}
          </div>
        </div>
        {run.preview_url ? (
          <iframe
            key={refresh}
            className={mobile ? "mobile-iframe" : ""}
            title={"Application " + side.toUpperCase()}
            src={run.preview_url}
            sandbox="allow-scripts allow-same-origin allow-forms allow-downloads"
            referrerPolicy="no-referrer"
          />
        ) : (
          <div className="preview-empty">
            <Monitor size={28} />
            <p>
              {run.status === "failed"
                ? "Preview unavailable"
                : "Waiting for the application server"}
            </p>
            <small>Check agent activity for updates.</small>
          </div>
        )}
      </div>
      {tab === "Source files" && (
        <div className="panel-content">
          {files?.length ? (
            <ul className="file-list">
              {files.map((file) => (
                <li key={file}>{file}</li>
              ))}
            </ul>
          ) : (
            <p>No source files to display.</p>
          )}
        </div>
      )}
      {(tab === "Terminal output" || tab === "Agent activity") && (
        <div className="panel-content" role="log">
          {visible.length ? (
            visible.map((event) => (
              <div className={"event " + event.kind} key={event.id}>
                {event.text}
              </div>
            ))
          ) : (
            <p>Activity will appear here.</p>
          )}
        </div>
      )}
      <Instruction
        label={"Follow up with agent " + side.toUpperCase()}
        disabled={!ready}
        submit={(text) => action("instructions", text)}
      />
    </section>
  );
}

export default function Home() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [catalog, setCatalog] = useState<Model[]>([]);
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [chosen, setChosen] = useState<Record<Side, string>>({ a: "", b: "" });
  const [keys, setKeys] = useState<Record<Side, string>>({ a: "", b: "" });
  const [reuse, setReuse] = useState(false);
  const [tools, setTools] = useState<string[]>([]);
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [comparison, setComparison] = useState<Comparison>();
  const [owner, setOwner] = useState("");
  const [events, setEvents] = useState<Activity[]>([]);
  const [active, setActive] = useState<Side>("a");
  const [split, setSplit] = useState(50);
  const [online, setOnline] = useState(false);
  const [scriptReady, setScriptReady] = useState(false);
  const [challenge, setChallenge] = useState("");
  const widget = useRef<HTMLDivElement>(null);
  const widgetId = useRef<string | null>(null);
  const workspace = useRef<HTMLDivElement>(null);
  const sessionId = comparison?.id;

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      call("/api/models", { signal: controller.signal }).then((response) =>
        response.json(),
      ),
      call("/api/integrations", { signal: controller.signal }).then(
        (response) => response.json(),
      ),
    ])
      .then(([models, available]) => {
        setCatalog(models);
        setIntegrations(available);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(failure.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!scriptReady || !widget.current || !window.turnstile || comparison)
      return;
    const turnstile = window.turnstile;
    const id = turnstile.render(widget.current, {
      sitekey: siteKey,
      action: "comparison",
      callback: setChallenge,
      "expired-callback": () => setChallenge(""),
    });
    widgetId.current = id;
    return () => {
      turnstile.remove(id);
      widgetId.current = null;
    };
  }, [scriptReady, comparison]);

  useEffect(() => {
    if (!sessionId || !owner) return;
    let stopped = false;
    let cursor = 0;
    let socket: WebSocket;
    let retry: ReturnType<typeof setTimeout>;
    let lastActive = 0;
    const activity = () => {
      if (
        socket?.readyState === WebSocket.OPEN &&
        Date.now() - lastActive > 15_000
      ) {
        socket.send("active");
        lastActive = Date.now();
      }
    };
    const connect = () => {
      const endpoint = new URL(
        api + "/" + sessionId + "/events",
        window.location.href,
      );
      endpoint.protocol = endpoint.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(endpoint);
      socket.onopen = () =>
        socket.send(JSON.stringify({ token: owner, after: cursor }));
      socket.onmessage = ({ data }) => {
        const update = JSON.parse(data) as {
          session: Comparison;
          events: Activity[];
        };
        setOnline(true);
        setComparison(update.session);
        if (update.events.length) {
          cursor = update.events[update.events.length - 1].id;
          setEvents((previous) => [...previous, ...update.events].slice(-240));
        }
      };
      socket.onclose = ({ code }) => {
        if (stopped) return;
        setOnline(false);
        if (code === 1000 || code === 1008) {
          setComparison(undefined);
          setOwner("");
          setError("This comparison has ended.");
        } else {
          retry = setTimeout(connect, 1500);
        }
      };
    };
    connect();
    window.addEventListener("pointerdown", activity);
    window.addEventListener("keydown", activity);
    return () => {
      stopped = true;
      clearTimeout(retry);
      socket?.close();
      window.removeEventListener("pointerdown", activity);
      window.removeEventListener("keydown", activity);
    };
  }, [sessionId, owner]);

  function select(side: Side, id: string) {
    setChosen((previous) => ({ ...previous, [side]: id }));
    setKeys((previous) => ({ ...previous, [side]: "" }));
  }

  async function start(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const models = sides.map((side) => {
        const model = catalog.find(
          (item) => item.provider + "/" + item.id === chosen[side],
        );
        if (!model) throw new Error("Select both models.");
        return {
          provider: model.provider,
          model: model.id,
          api_key: keys[side] || null,
        };
      });
      if (reuse && models[0].provider === models[1].provider)
        models[1].api_key = keys.a;
      const response = await call(api, {
        method: "POST",
        body: JSON.stringify({
          prompt,
          models,
          integrations: tools,
          turnstile_token: challenge,
        }),
      });
      const { token, ...session }: Comparison & { token: string } =
        await response.json();
      setEvents([]);
      setKeys({ a: "", b: "" });
      setComparison(session);
      setOwner(token);
      setOnline(false);
    } catch (failure) {
      setError((failure as Error).message);
      if (widgetId.current) window.turnstile?.reset(widgetId.current);
      setChallenge("");
    } finally {
      setBusy(false);
    }
  }

  async function request(suffix = "", options: RequestInit = {}) {
    setError("");
    try {
      return await call(api + "/" + sessionId + suffix, options, owner);
    } catch (failure) {
      setError((failure as Error).message);
      throw failure;
    }
  }

  async function action(side: Side | "both", name: string, text?: string) {
    await request("/" + side + "/" + name, {
      method: "POST",
      body: text ? JSON.stringify({ prompt: text }) : undefined,
    });
  }

  async function download(side: Side | "both") {
    try {
      const response = await request("/" + side + "/export");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "vibebench-" + side + ".zip";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch {
      /* Reported by request. */
    }
  }

  const selectedA = catalog.find(
    (model) => model.provider + "/" + model.id === chosen.a,
  );
  const selectedB = catalog.find(
    (model) => model.provider + "/" + model.id === chosen.b,
  );
  const canReuse = Boolean(
    selectedA?.requires_key && selectedB?.provider === selectedA.provider,
  );
  const reusableKey = reuse && canReuse ? keys.a : null;
  const alert: ReactNode = error && (
    <p className="error" role="alert">
      {error}
    </p>
  );

  return (
    <div className="app" data-theme={theme}>
      {siteKey && (
        <Script
          src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"
          onReady={() => setScriptReady(true)}
        />
      )}
      <header className="topbar">
        <Link className="wordmark" href="/" aria-label="VibeBench home">
          <span>
            <Columns2 size={18} />
          </span>
          VibeBench
        </Link>
        <div className="topbar-actions">
          <a
            href="https://github.com/shrouk-w/VibeBench"
            target="_blank"
            rel="noreferrer"
          >
            GitHub <ArrowUpRight size={14} />
          </a>
          <Button
            variant="ghost"
            aria-label={theme === "dark" ? "Use light theme" : "Use dark theme"}
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </Button>
        </div>
      </header>
      {comparison ? (
        <main className="workspace">
          <div className="workspace-heading">
            <div>
              <h1>Comparison workspace</h1>
              <p>
                {!online
                  ? "Connecting to agents…"
                  : comparison.expires_in < 120
                    ? "Session expires in " + comparison.expires_in + " seconds"
                    : "Live agent updates"}
              </p>
            </div>
            <div className="workspace-actions">
              <Button variant="outline" onClick={() => void download("both")}>
                <ArrowDownToLine size={16} /> Export both
              </Button>
              <Button
                variant="outline"
                onClick={async () => {
                  try {
                    await request("", { method: "DELETE" });
                    setComparison(undefined);
                    setOwner("");
                  } catch {
                    /* Reported by request. */
                  }
                }}
              >
                <X size={16} /> End session
              </Button>
            </div>
          </div>
          {alert}
          <div className="mobile-switch" aria-label="Visible application">
            {sides.map((side) => (
              <Button
                key={side}
                variant={active === side ? "default" : "outline"}
                onClick={() => setActive(side)}
              >
                Application {side.toUpperCase()}
              </Button>
            ))}
          </div>
          <div
            className="workspace-grid"
            ref={workspace}
            style={{ "--split": split + "%" } as React.CSSProperties}
          >
            {sides.map((side) => (
              <Panel
                key={side}
                side={side}
                events={events}
                run={comparison.runs[side]}
                active={active === side}
                action={(name, text) => action(side, name, text)}
                download={() => download(side)}
                loadFiles={() =>
                  request("/" + side + "/files").then((response) =>
                    response.json(),
                  )
                }
              />
            ))}
            <div
              className="divider"
              role="separator"
              aria-label="Resize application panels"
              tabIndex={0}
              aria-orientation="vertical"
              aria-valuemin={25}
              aria-valuemax={75}
              aria-valuenow={split}
              onKeyDown={(event) => {
                if (event.key !== "ArrowRight" && event.key !== "ArrowLeft")
                  return;
                event.preventDefault();
                setSplit((value) =>
                  Math.min(
                    75,
                    Math.max(25, value + (event.key === "ArrowRight" ? 2 : -2)),
                  ),
                );
              }}
              onPointerDown={(event) =>
                event.currentTarget.setPointerCapture(event.pointerId)
              }
              onPointerMove={(event) => {
                const bounds = workspace.current?.getBoundingClientRect();
                if (
                  !bounds ||
                  !event.currentTarget.hasPointerCapture(event.pointerId)
                )
                  return;
                setSplit(
                  Math.round(
                    Math.min(
                      75,
                      Math.max(
                        25,
                        ((event.clientX - bounds.left) / bounds.width) * 100,
                      ),
                    ),
                  ),
                );
              }}
            />
          </div>
          <Instruction
            label="Follow up with both agents"
            disabled={sides.some(
              (side) =>
                !["ready", "stopped", "failed"].includes(
                  comparison.runs[side].status,
                ),
            )}
            submit={(text) => action("both", "instructions", text)}
          />
        </main>
      ) : (
        <main className="landing">
          <section className="intro">
            <h1>
              Same prompt.
              <br />
              Different models.
              <br />
              <em>Real applications.</em>
            </h1>
            <p>
              Give two coding agents the same brief. Try their applications side
              by side and decide which works better for you.
            </p>
          </section>
          <form className="setup" onSubmit={start}>
            <div className="setup-heading">
              <Terminal size={17} />
              <h2>New comparison</h2>
            </div>
            <div className="setup-body">
              <label className="prompt-label" htmlFor="prompt">
                <Braces size={16} /> Application prompt
              </label>
              <textarea
                id="prompt"
                required
                minLength={1}
                maxLength={12000}
                rows={5}
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="Describe the web application you want both agents to build…"
              />
              <div className="models">
                {sides.map((side) => (
                  <ModelSelect
                    key={side}
                    side={side}
                    catalog={catalog}
                    selected={chosen[side]}
                    select={(id) => select(side, id)}
                    value={
                      side === "b" && reusableKey !== null
                        ? reusableKey
                        : keys[side]
                    }
                    setValue={(key) =>
                      setKeys((previous) => ({
                        ...previous,
                        [side === "b" && reusableKey !== null ? "a" : side]:
                          key,
                      }))
                    }
                  />
                ))}
              </div>
              {canReuse && (
                <label className="check">
                  <input
                    type="checkbox"
                    checked={reuse}
                    onChange={(event) => setReuse(event.target.checked)}
                  />{" "}
                  Use the same API key for both agents
                </label>
              )}
              {!!integrations.length && (
                <details className="integrations">
                  <summary>MCP integrations</summary>
                  {integrations.map((tool) => (
                    <label className="check" key={tool.id}>
                      <input
                        type="checkbox"
                        disabled={!tool.available}
                        checked={tools.includes(tool.id)}
                        onChange={(event) =>
                          setTools((previous) =>
                            event.target.checked
                              ? [...previous, tool.id]
                              : previous.filter((id) => id !== tool.id),
                          )
                        }
                      />
                      <span>
                        <strong>
                          {tool.name}
                          {!tool.available && " · Unavailable"}
                        </strong>
                        <small>{tool.description}</small>
                      </span>
                    </label>
                  ))}
                </details>
              )}
              {siteKey && <div ref={widget} />}
              {alert}
              <div className="setup-footer">
                <p>
                  Sessions expire automatically. Your selected provider may bill
                  API usage or retain submitted prompts.
                </p>
                <Button
                  type="submit"
                  disabled={
                    loading ||
                    busy ||
                    !prompt.trim() ||
                    !chosen.a ||
                    !chosen.b ||
                    Boolean(siteKey && !challenge)
                  }
                >
                  {busy || loading ? (
                    <LoaderCircle className="spinner" size={16} />
                  ) : (
                    <Play size={16} />
                  )}{" "}
                  Start comparison
                </Button>
              </div>
            </div>
          </form>
        </main>
      )}
    </div>
  );
}
