import { defineAgent } from "@openagent/extension-sdk";

// Policy notes (enforced server-side by the browser policy engine):
// - navigation limited to security.allowed_hosts (shop.example.com)
// - no file uploads, no downloads executed, no credential fields touched
// - every run is observed + audited; high-risk actions need approval
export default defineAgent({
  name: "price-watch",
  description: "Extract the price from a product page.",
  model: { default: "gpt-4o-mini" },
  systemPrompt: "Navigate, extract price + availability, never submit forms.",
  async onRun(ctx, input: { url: string }) {
    if (!input.url.startsWith("https://shop.example.com/")) throw new Error("URL outside allowlist");
    const page = await ctx.browser.goto(input.url);
    const data = await ctx.browser.extract(".price");
    return { title: page.title, price: data.text };
  },
});
