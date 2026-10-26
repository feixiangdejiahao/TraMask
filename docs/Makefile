LATEXMK ?= latexmk
DECK := 20261001_test_augmentation_slides
DECK_DIR := archive

.PHONY: all clean

all: $(DECK_DIR)/$(DECK).pdf

$(DECK_DIR)/$(DECK).pdf: $(DECK_DIR)/$(DECK).tex
	$(LATEXMK) -pdf -interaction=nonstopmode -halt-on-error -outdir=build $<
	cp build/$(DECK).pdf $@

clean:
	$(LATEXMK) -C -outdir=build $(DECK_DIR)/$(DECK).tex
