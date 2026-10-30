// Stage for frontdesk-list.jpg (tools/site_screenshots.sh): the ranked inbox as the About page's
// hero. Stars the SOW thread (Gmail) and the vendor channel thread (Slack) so both kinds show a
// filled star, drops the demo banner (the caption says it is synthetic), and returns a height
// that ends just below the sixth "Needs you" card, so no card is cut in half.
const wait = ms => new Promise(ok => setTimeout(ok, ms));
const cards = () => [...document.querySelectorAll("main li.card")];
for (const text of ["Signed SOW", "#analytics-vendor"]) {
  const li = cards().find(n => n.textContent.includes(text));
  if (!li) throw new Error("no card with " + text);
  li.querySelector(":scope > button.star").click();
  for (let i = 0; i < 50 && !cards().find(n => n.textContent.includes(text))
       .querySelector(":scope > button.star.on:not(.pending)"); i++) await wait(50);
}
await wait(300);
document.querySelector(".demo-banner")?.remove();
document.getElementById("toast").hidden = true;
for (const n of document.querySelectorAll("li.card.current")) n.classList.remove("current");
if (document.activeElement) document.activeElement.blur();
const sixth = cards()[5].getBoundingClientRect();
return sixth.bottom + window.scrollY + 5;
