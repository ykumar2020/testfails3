# testFAILS3 paper

The manuscript is generated only from the frozen run at
`../data/runs/20261013T040244Z.json`.

Build from this directory:

```powershell
python make_figures.py
pdflatex -interaction=nonstopmode -halt-on-error testfails3.tex
pdflatex -interaction=nonstopmode -halt-on-error testfails3.tex
```

The figures are regenerated from the JSON evidence. The manuscript reports a
score only for the provider with completed cases. The Gemini HTTP 402 attempt
is retained as zero coverage with no score.
