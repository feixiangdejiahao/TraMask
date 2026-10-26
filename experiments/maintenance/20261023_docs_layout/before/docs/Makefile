LATEXMK ?= latexmk
DECK := combination_testing_research

.PHONY: all clean

all: $(DECK).pdf

$(DECK).pdf: $(DECK).tex
	$(LATEXMK) -pdf -interaction=nonstopmode -halt-on-error -outdir=build $<
	cp build/$(DECK).pdf $@

clean:
	$(LATEXMK) -C -outdir=build $(DECK).tex
