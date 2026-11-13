CLANG ?= clang
OUTPUT ?= syn_rewrite.o
MULTIARCH := $(shell gcc -dumpmachine)
CPPFLAGS += -isystem /usr/include/$(MULTIARCH)
CFLAGS := -target bpf -O2 -g -Wall -Wextra -Werror

.PHONY: all analyze clean
all: $(OUTPUT)

$(OUTPUT): syn_rewrite.c
	@mkdir -p $(dir $@)
	$(CLANG) $(CPPFLAGS) $(CFLAGS) -c $< -o $@

analyze:
	$(CLANG) $(CPPFLAGS) $(CFLAGS) --analyze syn_rewrite.c -o /dev/null

clean:
	rm -f $(OUTPUT)
