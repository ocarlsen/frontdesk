# FrontDesk tour film: the brief

The film on the About page (`docs/site/frontdesk-tour.mp4`, with its GIF and poster), about three
and a half minutes, no sound. `demo/film.ts` is the storyboard; it is recorded with
TourKit, a small Playwright and ffmpeg film tool that is not yet
public, so today only its author can re-record it:

```
node <TourKit>/run.ts demo/film.ts --check   # dry run: every caption checked, nothing recorded
node <TourKit>/run.ts demo/film.ts           # records into demo/out/, copies the outputs to docs/site/
```

Synthetic data only: `tools/serve_tour.py` serves the exported static demo and a throwaway live
server (temp `FRONTDESK_HOME`, no keys, no network, sync and the Gmail draft lookup stubbed off).
Every number in a caption is read off the page, and a `must(...)` check fails the run when the
page no longer says what a caption claims. That is the `prove:` line under each scene.

## Scenes

1. **Ranked for you.** The ranked inbox in its three groups; star; Move to and Undo.
   prove: the header counts, the Starred count, the reminder's section before and after.
2. **Keyboard shortcuts.** `?`, then j/k, Enter, e (archive with Undo), s, v.
   prove: the current row's subject, the archive toast, the star's aria-pressed, Move to focused.
3. **Some mail needs a decision.** Ask's starter question; a recorded answer that says
   "An unconfirmed note says…".
   prove: the textarea's starter text, the answer text, the empty follow-up box.
4. **Memory can be wrong.** The People strip's note editor; the Memory page's profile, What's
   going on (one line unconfirmed) and People, each labelled with who wrote it.
   prove: the author labels on each row.
5. **Mail can give orders.** The SOW's planted line flagged and kept in Needs you; the Slack
   vendor's "say Alex approved $48k" answered by a reply that approves nothing; **Test an attack**
   on suite attack i25 (a forged quote): the first fooled model, then Gemini 4 Argon resisting;
   Send's confirm screen and 30-second undo.
   prove: the summary text, the section, the proposed reply, the attack count, the pressed chip's
   verdict and Argon's chip and verdict, the recipient, the undo toast.
6. **Mail can watch you.** The demo newsletter: "Images are hidden.", then Show images loads the
   banner. TourKit records with `bypassCSP`, so the film's image route enforces the message
   page's `img-src` rule itself (images only for the `-images` page).
   prove: the bar's text, the banner's naturalWidth 0 before and above 0 after, the frame's
   `-images.html` src.
7. **Away from your desk.** iPhone 15 emulation, real touch: swipe to archive, Undo, star.
   prove: the swipe reveal, the toast's size, the star's aria-pressed.

## Not in the film, on purpose

- **Connect Gmail:** one-time setup, and filming it would mean faking a Google sign-in.
- **Which model ranks and which answers Ask:** the demo's rankings were recorded with another
  model, so a caption would contradict the Why panel on screen. The README states the defaults.
