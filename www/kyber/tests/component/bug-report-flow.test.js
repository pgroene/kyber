import { makePanel } from "../helpers.js";

const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("_openBugReportFlow", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("defaults bundle upload to OFF and shows bundle name", async () => {
    const { element } = makePanel();
    await element._openBugReportFlow("req-123");

    const checkbox = element.shadowRoot.querySelector("#br-include-bundle");
    expect(checkbox).not.toBeNull();
    expect(checkbox.checked).toBe(false);
    expect(element.shadowRoot.querySelector(".bug-report-bundle-name").textContent).toContain("kyber-debug-req-123.zip");
  });

  it("sends include_bundle=false by default with bundle_name", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ title: "Bug title", body: "Bug body", similar_issues: [], bundle_available: true }),
    }));
    const { element } = makePanel();
    await element._openBugReportFlow("req-999");

    element.shadowRoot.querySelector("#br-happened").value = "The action failed.";
    element.shadowRoot.querySelector("#br-submit").click();
    await flushPromises();
    await flushPromises();

    const bugCall = fetch.mock.calls.find((call) => call[0] === "/api/kyber/debug/bug-report");
    const payload = JSON.parse(bugCall[1].body);
    expect(payload.include_bundle).toBe(false);
    expect(payload.bundle_name).toBe("kyber-debug-req-999.zip");
  });

  it("sends include_bundle=true when checkbox is enabled", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ title: "Bug title", body: "Bug body", similar_issues: [], bundle_available: true }),
    }));
    const { element } = makePanel();
    await element._openBugReportFlow("req-1000");

    element.shadowRoot.querySelector("#br-include-bundle").checked = true;
    element.shadowRoot.querySelector("#br-happened").value = "The action failed.";
    element.shadowRoot.querySelector("#br-submit").click();
    await flushPromises();
    await flushPromises();

    const bugCall = fetch.mock.calls.find((call) => call[0] === "/api/kyber/debug/bug-report");
    const payload = JSON.parse(bugCall[1].body);
    expect(payload.include_bundle).toBe(true);
    expect(payload.bundle_name).toBe("kyber-debug-req-1000.zip");
  });
});
