# Reading Reference PDFs

Papers and slides live in `master_supporting_docs/supporting_papers/` and `supporting_slides/`.

- **Read them with the Read tool.** It reads PDFs natively, including charts and tables. For a
  document over about 20 pages, pass `pages` ranges (at most 20 pages per call), e.g. `"1-20"`,
  then `"21-40"`. `pdfinfo file.pdf | grep Pages` gives the length.
- **Read selectively.** Abstract, introduction, and the sections the task needs come first;
  appendices and references only when the task calls for them.
- **If a read fails** (a corrupt or unusual PDF), split it with
  `pdftk file.pdf burst output part_%03d.pdf` or Ghostscript (`gs -sDEVICE=pdfwrite -dFirstPage=N
  -dLastPage=M ...`) and read the parts. Note any pages you could not read rather than skipping them
  silently.
