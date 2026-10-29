// For tools/site_screenshots.sh only (never part of the export): shows just the injection thread, opened.
setTimeout(() => {
  const li = [...document.querySelectorAll("li")].find(n => n.textContent.includes("Signed SOW"));
  if (!li) return;
  (li.querySelector(".row") || li).click();
  setTimeout(() => {
    for (const n of document.querySelectorAll("header, .demo-banner, main h2, .sectionhead, .expandall, .linkbtn")) n.style.display = "none";
    for (const n of document.querySelectorAll("main li")) if (n !== li && !n.contains(li)) n.style.display = "none";
    for (const n of document.querySelectorAll("main section, main ul")) if (!n.contains(li)) n.style.display = "none";
    document.querySelector("main").style.paddingTop = "12px";
    window.scrollTo(0, 0);
  }, 700);
}, 900);
