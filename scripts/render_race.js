/* Render the two jersey races to PNG for the Sunday email.
 *
 * Email clients do not run JavaScript, so the animated chart cannot travel.
 * This screenshots race/still.html, which loads the SAME race.js the live
 * pages use, so the picture in the email can never drift from the chart on
 * the site.
 *
 * Usage: node scripts/render_race.js [outdir]
 */
const {chromium} = require("playwright");
const path = require("path");
const fs = require("fs");

(async () => {
  const outdir = process.argv[2] || "race";
  const url = "file://" + path.resolve("race/still.html");
  // PW_CHROMIUM lets a machine with a prebuilt browser point at it. On a CI
  // runner the workflow installs chromium and the default launch finds it.
  const exe = process.env.PW_CHROMIUM;
  const browser = await chromium.launch(exe ? {executablePath: exe} : {});
  let bad = 0;
  for (const [metric, name] of [["miles", "green.png"], ["feet", "polka.png"]]) {
    const page = await browser.newPage({viewport: {width: 1000, height: 700},
                                        deviceScaleFactor: 1.5});
    const errs = [];
    page.on("pageerror", e => errs.push(e.message));
    await page.goto(url + "?m=" + metric, {waitUntil: "load"});
    try {
      await page.waitForSelector('html[data-ready="1"]', {timeout: 15000});
    } catch (e) {
      console.error("[" + metric + "] chart never became ready");
      bad++; await page.close(); continue;
    }
    await page.waitForTimeout(900);          // let the webfonts settle
    const el = await page.$("#race");
    const out = path.join(outdir, name);
    await el.screenshot({path: out});
    const kb = Math.round(fs.statSync(out).size / 1024);
    console.log("[" + metric + "] -> " + out + "  " + kb + " KB" +
                (errs.length ? "  PAGE ERROR: " + errs[0] : ""));
    if (errs.length) bad++;
    await page.close();
  }
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
