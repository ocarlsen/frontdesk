// For tools/article_screenshots.py only: opens the staged thread and its Ask panel, hides the
// rest. ?notes=1 also opens "Your notes on these people" and scrolls to it.
setTimeout(() => {
  const li = [...document.querySelectorAll("main li")].find(n => n.textContent.includes("Cooking afternoon"));
  if (!li) return;
  (li.querySelector(".row") || li).click();
  setTimeout(() => {
    const ask = li.querySelector("details.ask");
    ask.open = true;
    setTimeout(() => {
      for (const n of document.querySelectorAll("header, .demo-banner, main h2, .linkbtn")) n.style.display = "none";
      for (const n of document.querySelectorAll("main li")) if (n !== li && !n.contains(li)) n.style.display = "none";
      for (const n of document.querySelectorAll("main section, main ul")) if (!n.contains(li)) n.style.display = "none";
      for (const n of li.querySelectorAll(".summary, .fullthread, .why, .reply")) n.style.display = "none";
      document.querySelector("main").style.paddingTop = "12px";
      // Crop each answer to its opening (the full text is in the eval report) and hide the
      // composer, so the frame shows the attribution and, with ?notes=1, the note's label.
      for (const n of li.querySelectorAll(".answertext")) {
        n.style.maxHeight = "8.6em"; n.style.overflow = "hidden";
        n.style.maskImage = "linear-gradient(to bottom, black 70%, transparent)";
      }
      for (const n of li.querySelectorAll(".askbody > textarea, .askbody > .actions")) n.style.display = "none";
      if (location.search.includes("notes=1")) {
        const nd = li.querySelector("details.notes");
        if (nd) nd.open = true;
      }
      window.scrollTo(0, 0);
    }, 1500);
  }, 600);
}, 900);
