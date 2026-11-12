CLANG ?= clang
MULTIARCH ?= $(shell gcc -dumpmachine 2>/dev/null)
CPPFLAGS += $(if $(MULTIARCH),-isystem /usr/include/$(MULTIARCH))
CFLAGS := -target bpf -O2 -g -Wall -Wextra -Werror -fno-stack-protector -fno-unwind-tables

.PHONY: all clean FORCE
all: syn_rewrite.o
# FORCE: never silently reuse a bundled/stale object. Keep BTF/debug information.
syn_rewrite.o: syn_rewrite.c FORCE
	@command -v $(CLANG) >/dev/null || { echo 'Missing clang with BPF target support. Configure CLANG explicitly.' >&2; exit 1; }
	@tmp=$$(mktemp ./syn_rewrite.XXXXXX.o); trap 'rm -f "$$tmp"' EXIT INT TERM; \
	$(CLANG) $(CPPFLAGS) $(CFLAGS) -fdebug-prefix-map=$(CURDIR)=. -c $< -o "$$tmp" && mv "$$tmp" $@
clean:
	rm -f syn_rewrite.o
