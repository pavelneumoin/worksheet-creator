# Computer Modern Unicode

Original, unmodified OpenType fonts, CM Unicode 0.7.0, Andrey V. Panov and the original Metafont authors (see OFL.txt).
Source: [CTAN cm-unicode](https://ctan.org/pkg/cm-unicode), downloaded from
`https://mirrors.ctan.org/fonts/cm-unicode.zip` on 2026-10-22.

`cmunrm`, `cmunbx`, `cmunti`, `cmunbi`: CMU Serif regular, bold, italic, bold italic.
`cmuntt`: CMU Typewriter Text, for the printed edition identifier.
Redistributed with the original [SIL Open Font License](OFL.txt).
No font modifications or renaming. Mathematics uses TeX's Computer Modern math fonts.

The compiler copies this directory into its temporary `fonts/` directory. No system
font install or network access is needed. To compile a downloaded `.tex` independently,
put these OTF files in `fonts/` beside it, or install CMU Serif and CMU Typewriter Text,
then run XeLaTeX twice to resolve page totals.
