// Stage for frontdesk-thread.jpg (tools/site_screenshots.sh): only the SOW thread with the
// planted instruction, opened, with "Why this ranking" (at the bottom of the thread) expanded.
// The Ask panel stays collapsed: the static demo has no model behind it.
const wait = ms => new Promise(ok => setTimeout(ok, ms));
const li = [...document.querySelectorAll("main li.card")].find(n => n.textContent.includes("Signed SOW"));
if (!li) throw new Error("no SOW card");
li.querySelector(":scope > .row").click();
for (let i = 0; i < 50 && !li.querySelector("details.why"); i++) await wait(50);
li.querySelector("details.why").open = true;
await wait(300);
for (const n of document.querySelectorAll("header, .demo-banner, main h2, .sectionhead, .expandall, .linkbtn")) {
  if (!li.contains(n)) n.style.display = "none";
}
for (const n of document.querySelectorAll("main li")) if (n !== li && !n.contains(li)) n.style.display = "none";
for (const n of document.querySelectorAll("main section, main ul, main > *")) {
  if (!n.contains(li)) n.style.display = "none";
}
document.querySelector("main").style.paddingTop = "12px";
document.getElementById("toast").hidden = true;
li.classList.remove("current");
if (document.activeElement) document.activeElement.blur();
window.scrollTo(0, 0);
