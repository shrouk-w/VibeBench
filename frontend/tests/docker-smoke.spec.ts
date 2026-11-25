import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";

function docker(args: string[]) {
  return execFileSync("docker", args, {
    encoding: "utf8",
    timeout: 15_000,
  }).trim();
}

const application = Buffer.from(
  `
  const { createServer } = require("node:http");
  const { createHash } = require("node:crypto");
  const html = '<title>Fixture</title><h1>Horse Discovery</h1><button>Favorite</button>'
    + '<p>Connecting</p><script>const out=document.querySelector("p");'
    + 'const ws=new WebSocket(location.origin.replace(/^http/,"ws")+"/activity");'
    + 'ws.onmessage=(event)=>out.textContent=event.data;'
    + 'document.querySelector("button").onclick=()=>out.textContent="Saved!";</script>';
  const server = createServer((_, res) => {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(html);
  });
  server.on("upgrade", (req, socket) => {
    const accept = createHash("sha1").update(req.headers["sec-websocket-key"]
      + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest("base64");
    socket.write("HTTP/1.1 101 Switching Protocols\\r\\nUpgrade: websocket\\r\\nConnection: Upgrade\\r\\nSec-WebSocket-Accept: " + accept + "\\r\\n\\r\\n");
    const text = Buffer.from("Live preview");
    socket.write(Buffer.concat([Buffer.from([0x81, text.length]), text]));
  });
  server.listen(4173, "0.0.0.0");
`,
).toString("base64");

test("isolates two Docker sandboxes and proxies fixture applications", async ({
  page,
  request,
  baseURL,
}) => {
  test.skip(
    process.env.VB_DOCKER_SMOKE !== "1",
    "Requires Docker Compose and an empty local slot",
  );
  const catalog = await (await request.get("/api/models")).json();
  const model = catalog.find((value: { free: boolean }) => value.free);
  expect(model).toBeTruthy();
  const origin = new URL(baseURL ?? "http://localhost:8080").origin;
  const started = await request.post("/api/comparisons", {
    headers: { Origin: origin },
    data: {
      prompt: "Local Docker smoke test. No application work is needed.",
      models: [
        { provider: model.provider, model: model.id },
        { provider: model.provider, model: model.id },
      ],
    },
  });
  expect(started.status()).toBe(201);
  const { id, token } = await started.json();
  expect(id).toMatch(/^[a-f0-9]{24}$/);
  const auth = { Authorization: "Bearer " + token, Origin: origin };
  const route = "/api/comparisons/" + id;
  const containers = ["vb-" + id + "-a", "vb-" + id + "-b"];
  try {
    for (const container of containers) {
      await expect
        .poll(() =>
          docker([
            "ps",
            "--filter",
            "name=" + container,
            "--format",
            "{{.Names}}",
          ]),
        )
        .toBe(container);
      docker([
        "exec",
        container,
        "node",
        "-e",
        'const fs=require("node:fs"); fs.writeFileSync("/workspace/server.cjs",Buffer.from(process.argv[1],"base64")); fs.writeFileSync("/workspace/.env","KEY=fixture"); fs.symlinkSync("/workspace/.env","/workspace/secret-link");',
        application,
      ]);
      docker(["exec", "-d", container, "node", "/workspace/server.cjs"]);
    }
    const destinations = containers.map((container) =>
      JSON.parse(
        docker([
          "inspect",
          "--format",
          "{{json .NetworkSettings.Networks}}",
          container,
        ]),
      ),
    );
    const names = destinations.map((entry) => Object.keys(entry));
    expect(names[0]).toHaveLength(1);
    expect(names[1]).toHaveLength(1);
    expect(names[0]).not.toEqual(names[1]);
    const address = destinations[1][names[1][0]].IPAddress;
    expect(
      docker([
        "exec",
        containers[0],
        "sh",
        "-c",
        'curl -fsS --noproxy "*" --max-time 2 "$1" >/dev/null 2>&1 && echo open || echo blocked',
        "sh",
        "http://" + address + ":4173",
      ]),
    ).toBe("blocked");
    expect(
      docker([
        "exec",
        containers[0],
        "sh",
        "-c",
        'curl -fsS --noproxy "*" --max-time 2 http://169.254.169.254/ >/dev/null 2>&1 && echo open || echo blocked',
      ]),
    ).toBe("blocked");
    expect(
      docker([
        "exec",
        containers[0],
        "curl",
        "-sS",
        "-o",
        "/dev/null",
        "-w",
        "%{http_code}",
        "--max-time",
        "10",
        "https://registry.npmjs.org/pnpm",
      ]),
    ).toBe("200");

    for (const side of ["a", "b"]) {
      let preview: string;
      await expect
        .poll(async () => {
          const state = await (
            await request.get(route, { headers: auth })
          ).json();
          preview = state.runs[side].preview_url;
          return Boolean(preview);
        })
        .toBeTruthy();
      await page.goto(preview!);
      await expect(
        page.getByRole("heading", { name: "Horse Discovery" }),
      ).toBeVisible();
      await expect(
        page.getByText("Live preview", { exact: true }),
      ).toBeVisible();
      await page.getByRole("button", { name: "Favorite" }).click();
      await expect(page.getByText("Saved!", { exact: true })).toBeVisible();
    }
    expect((await request.get(route + "/a/files")).status()).toBe(404);
    const listing = await request.get(route + "/a/files", { headers: auth });
    const names = await listing.json();
    expect(names).toContain("server.cjs");
    expect(names).not.toContain("secret-link");
    const source = await request.get(route + "/a/file?path=server.cjs", {
      headers: auth,
    });
    expect((await source.json()).content).toContain("createServer");
    const archive = await request.get(route + "/both/export", {
      headers: auth,
    });
    expect(archive.ok()).toBeTruthy();
    const zip = await archive.body();
    expect(zip.subarray(0, 2).toString()).toBe("PK");
    expect(zip.includes(Buffer.from("a/server.cjs"))).toBeTruthy();
    expect(zip.includes(Buffer.from("b/server.cjs"))).toBeTruthy();
    expect(zip.includes(Buffer.from("secret-link"))).toBeFalsy();
    expect(zip.includes(Buffer.from(".env"))).toBeFalsy();
  } finally {
    expect((await request.delete(route, { headers: auth })).status()).toBe(204);
  }
  for (const container of containers) {
    expect(
      docker([
        "ps",
        "-a",
        "--filter",
        "name=" + container,
        "--format",
        "{{.Names}}",
      ]),
    ).toBe("");
  }
});
