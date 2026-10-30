// Stage for tools/article_screenshots.py (run by tools/capture.mjs): opens the seeded thread and
// its Ask panel, hides the rest of the page. ?notes=1 also opens "Your notes on these people".
// Each answer is cropped to its opening (the full text is in the eval report); the follow-up box
// below it stays, as on the real page.
const wait = ms => new Promise(ok => setTimeout(ok, ms));
const until = async (f, what) => {
  for (let i = 0; i < 100; i++) { const v = f(); if (v) return v; await wait(50); }
  throw new Error("timed out waiting for " + what);
};
const li = [...document.querySelectorAll("main li.card")].find(n => n.textContent.includes("Cooking afternoon"));
if (!li) throw new Error("no seeded thread");
li.querySelector(":scope > .row").click();
const ask = await until(() => li.querySelector("details.ask"), "the Ask panel");
ask.open = true;
await until(() => li.querySelector(".answertext") && li.querySelector("details.notes"), "the Ask history");
for (const n of document.querySelectorAll("header, .demo-banner, main h2, .sectionhead, .linkbtn")) {
  if (!li.contains(n)) n.style.display = "none";
}
for (const n of document.querySelectorAll("main li")) if (n !== li && !n.contains(li)) n.style.display = "none";
for (const n of document.querySelectorAll("main section, main ul, main > *")) {
  if (!n.contains(li)) n.style.display = "none";
}
for (const n of li.querySelectorAll(".summary, .fullthread, .why, .reply")) n.style.display = "none";
document.querySelector("main").style.paddingTop = "12px";
for (const n of li.querySelectorAll(".answertext")) {
  n.style.maxHeight = "8.6em"; n.style.overflow = "hidden";
  n.style.maskImage = "linear-gradient(to bottom, black 70%, transparent)";
}
if (location.search.includes("notes=1")) li.querySelector("details.notes").open = true;
document.getElementById("toast").hidden = true;
li.classList.remove("current");
if (document.activeElement) document.activeElement.blur();
window.scrollTo(0, 0);
await wait(100);
return li.getBoundingClientRect().bottom + window.scrollY + 24;   // the card, not the empty page
