import assert from "node:assert/strict";

// Run against the disposable store created by the recovery fixture, never a live server.
const base = process.argv[2];
const output = process.argv[3];
assert.equal(new URL(base).hostname, "127.0.0.1");
assert.equal(new URL(base).protocol, "http:");
assert.notEqual(new URL(base).port, "8799", "The launchd server is not a test fixture");
assert.ok(output?.startsWith("/private/tmp/ontologylab-recovery-"));
const view = new Bun.WebView({
  width: 1280, height: 900,
  backend: { type: "chrome", url: false },
});
const failures = [];

async function ready(expression) {
  await view.evaluate(`new Promise((resolve, reject) => {
    const matches = () => Boolean(${expression});
    if (matches()) return resolve();
    const observer = new MutationObserver(() => {
      if (matches()) { observer.disconnect(); clearTimeout(timer); resolve(); }
    });
    const timer = setTimeout(() => {
      observer.disconnect(); reject(new Error(${JSON.stringify(expression)}));
    }, 5000);
    observer.observe(document.body, { childList: true, subtree: true, attributes: true });
  })`);
}

async function api(path, body) {
  return view.evaluate(`fetch('/api' + ${JSON.stringify(path)}, {
    method: ${JSON.stringify(body === undefined ? "GET" : "POST")},
    headers: {'Content-Type':'application/json'},
    ${body === undefined ? "" : `body: JSON.stringify(${JSON.stringify(body)}),`}
  }).then(async response => {
    if (!response.ok) throw new Error(response.status + ':' + await response.text());
    return response.json();
  })`);
}

async function check(name, run) {
  try {
    await run();
    console.log("QA_PASS", name);
  } catch (error) {
    failures.push(name);
    console.error("QA_FAIL", name, error);
  }
}

async function capture(name) {
  await Bun.write(`${output}/${name}.png`, await view.screenshot());
}

async function mobileLayout() {
  const widths = await view.evaluate(`({
    document: document.documentElement.scrollWidth,
    viewport: innerWidth,
    main: document.querySelector('main').scrollWidth,
    available: document.querySelector('main').clientWidth,
  })`);
  assert.equal(widths.document, widths.viewport, JSON.stringify(widths));
  assert.equal(widths.main, widths.available, JSON.stringify(widths));
}

const id = name => `recovery-recovery${name.toLowerCase()}`;
try {
  await view.navigate(base);
  await ready(`document.querySelector('section[aria-label="저장소 요약 수치"]')`);
  const documents = await api("/documents");
  assert.equal(documents.documents.length, 1);
  assert.equal(documents.documents[0].title, "Recovery QA");

  // Restore only the explicitly named QA proposals so each invocation exercises decisions.
  for (const name of ["Alpha", "Beta", "Gamma", "Delta"]) {
    const detail = await api(`/entity/${id(name)}/review`);
    if (detail.entity.status !== "proposed") await api("/proposals/reopen", { id: id(name) });
  }
  await view.reload();
  await ready(`document.querySelectorAll('tbody tr').length === 5`);

  await check("home store-wide counts", async () => {
    const counts = (await api("/proposals?limit=5")).counts;
    assert.equal(counts.nodes_proposed, 4);
    assert.equal(counts.edges_proposed, 1);
    const numbers = await view.evaluate(`Array.from(document.querySelectorAll('section[aria-label="저장소 요약 수치"] .text-2xl')).map(e=>Number(e.textContent))`);
    assert.deepEqual(numbers, [1, 4, 5, 0]);
    await capture("home-populated-desktop");
  });

  await check("home conflict is visible and preserves authority", async () => {
    const before = (await api("/proposals")).counts;
    await view.click('tbody tr:last-child button:first-child');
    await ready(`document.querySelector('[role="alert"]')`);
    assert.deepEqual((await api("/proposals")).counts, before);
    assert.ok(!(await view.evaluate("document.querySelector('[role=\"alert\"]').textContent")).includes("[object Object]"));
    await capture("home-conflict");
  });

  for (const [name, action, status] of [["Alpha", "승인", "verified"], ["Beta", "승인", "verified"], ["Delta", "거부", "rejected"]]) {
    await check(`home decision ${name}`, async () => {
      const selector = `button[aria-label="Recovery${name} ${action}"]`;
      await view.click(selector);
      await ready(`!document.querySelector(${JSON.stringify(selector)})`);
      assert.equal((await api(`/entity/${id(name)}/review`)).entity.status, status);
    });
  }

  await check("home mobile table owns overflow", async () => {
    await view.resize(375, 812);
    await capture("home-mobile-top");
    await view.scrollTo("table");
    await capture("home-mobile-review");
    await mobileLayout();
    const wrapper = await view.evaluate(`(() => {
      const table = document.querySelector("table");
      const parent = table.parentElement;
      return { scroll: getComputedStyle(parent).overflowX, width: parent.clientWidth, content: parent.scrollWidth };
    })()`);
    assert.equal(wrapper.scroll, "auto");
    assert.ok(wrapper.content > wrapper.width);
  });

  await check("home links have readable action color", async () => {
    const color = await view.evaluate(`getComputedStyle(document.querySelector('main a[href="/review"]')).color`);
    assert.notEqual(color, "rgb(53, 53, 50)", "The link must not use the dark accent surface as text");
  });

  await view.resize(1280, 900);
  await view.click('nav a[href="/graph"]');
  await ready(`document.querySelectorAll('g.g-node').length === 3`);
  await check("graph renders real nodes and relation", async () => {
    assert.equal(await view.evaluate("document.querySelectorAll('line.g-edge').length"), 1);
    await capture("graph-populated-desktop");
  });

  await check("graph latest selected node owns its detail", async () => {
    // Hold a genuine server response at the transport seam, not a hand-written fixture.
    await view.evaluate(`(() => {
      window.qaFetch = window.fetch;
      window.qaHeldReady = new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error("detail request not held")), 5000);
        window.qaHoldReady = () => { clearTimeout(timer); resolve(); };
      });
      window.qaConsumed = new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error("detail response not consumed")), 10000);
        window.qaConsume = () => { clearTimeout(timer); resolve(); };
      });
      window.fetch = async (...args) => {
        const response = await window.qaFetch(...args);
        if (String(args[0]).includes('/entity/${id("Alpha")}/review')) {
          await new Promise(resolve => {
            window.qaRelease = resolve;
            window.qaHoldReady();
          });
          const json = response.json.bind(response);
          response.json = async () => {
            const value = await json();
            window.qaConsume();
            return value;
          };
        }
        return response;
      };
    })()`);
    await view.evaluate(`document.querySelector('g[data-id="${id("Alpha")}"]').focus()`);
    await view.press("Enter");
    await view.evaluate("window.qaHeldReady");
    await view.evaluate(`document.querySelector('g[data-id="${id("Beta")}"]').focus()`);
    await view.press("Space");
    await ready(`document.querySelector('main [data-radix-scroll-area-viewport]')?.textContent.includes('RecoveryBeta')`);
    await view.evaluate(`window.qaRelease()`);
    await view.evaluate("window.qaConsumed");
    // A compositor capture is the render barrier after the genuine response was consumed.
    await capture("graph-selected-desktop");
    const detail = await view.evaluate(`document.querySelector('main [data-radix-scroll-area-viewport]').textContent`);
    assert.ok(detail.includes(id("Beta").slice(0, 18)), detail);
    await view.evaluate("window.fetch = window.qaFetch");
  });

  await check("graph filter keeps proposed objects out of verified view", async () => {
    const before = (await api("/proposals")).counts;
    await view.click('button[aria-pressed="true"]');
    await ready(`document.querySelectorAll('g.g-node').length === 2`);
    assert.equal(await view.evaluate("document.querySelectorAll('g.g-proposed, line.g-edge').length"), 0);
    assert.deepEqual((await api("/proposals")).counts, before);
    await capture("graph-verified-only");
    await view.click('button[aria-pressed="false"]');
    await ready(`document.querySelectorAll('g.g-node').length === 3`);
  });

  await check("graph search selects the real entity", async () => {
    await view.click('input[type="search"]');
    await view.type("RecoveryBeta");
    await ready(`document.querySelector('input[type="search"]').parentElement.querySelector("ul button")`);
    await view.click('main .relative ul button');
    await ready(`document.querySelector('g.g-selected')?.getAttribute('data-id') === '${id("Beta")}'`);
    await ready(`document.querySelector('main [data-radix-scroll-area-viewport]')?.textContent.includes('RecoveryBeta')`);
    await view.click('input[type="search"]');
    await view.cdp("Input.dispatchKeyEvent", {
      type: "keyDown", key: "a", code: "KeyA", modifiers: 4, commands: ["selectAll"],
    });
    await view.press("Backspace");
    assert.equal(await view.evaluate(`document.querySelector('input[type="search"]').value`), "");
  });

  await check("graph mobile selected layout", async () => {
    await view.resize(375, 812);
    await ready(`Array.from(document.querySelectorAll('g.g-node')).every(node => {
      const canvas = document.querySelector('svg.g-canvas').getBoundingClientRect();
      const box = node.getBoundingClientRect();
      return box.x >= canvas.x && box.right <= canvas.right &&
        box.y >= canvas.y && box.bottom <= canvas.bottom;
    })`);
    await capture("graph-mobile-top");
    await view.scrollTo('main > div > div:last-child > div:last-child');
    await capture("graph-mobile-detail");
    await mobileLayout();
    const detailHeight = await view.evaluate(`Array.from(document.querySelectorAll('[data-radix-scroll-area-viewport]')).at(-1).clientHeight`);
    assert.ok(detailHeight >= 100, `Detail viewport is only ${detailHeight}px high`);
  });

  await check("graph reload serves the application", async () => {
    await view.reload();
    await ready(`document.querySelector('h1') && document.querySelector('svg.g-canvas')`);
  });

  await check("sources navigation does not seed sample data", async () => {
    const before = (await api("/documents")).count;
    await view.resize(1280, 900);
    await view.click('nav a[href="/sources"]');
    await ready(`document.querySelector('#collect-source')`);
    await view.scrollTo("#collect-source");
    await capture("sources-collect-desktop");
    assert.equal((await api("/documents")).count, before);
    await view.resize(375, 812);
    await view.scrollTo("#collect-source");
    await capture("sources-collect-mobile");
  });
} finally {
  view.close();
}
assert.deepEqual(failures, [], "Browser regressions remain");
