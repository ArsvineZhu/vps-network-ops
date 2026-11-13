UV ?= uv
GO ?= go
NPM ?= npm
SHELLCHECK ?= shellcheck
SHFMT ?= shfmt
CLANG_FORMAT ?= clang-format
CLANG ?= clang
CADDY ?= caddy

GO_DIR := system/tcpfp/mirage-syn
SHELL_FILES := system/tcpfp/network.sh system/mihomo/renew-credential-refresh.sh.in
C_FILE := system/tcpfp/ebpf/syn_rewrite.c

.PHONY: fmt lint typecheck build test check

fmt:
	$(UV) run ruff check --select I --fix .
	$(UV) run ruff format .
	cd $(GO_DIR) && $(GO) tool goimports -w .
	$(SHFMT) -w $(SHELL_FILES)
	$(CLANG_FORMAT) -i $(C_FILE)
	$(CADDY) fmt --overwrite system/caddy/Caddyfile.example
	$(NPM) exec prettier -- --write .

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	cd $(GO_DIR) && test -z "$$($(GO) tool goimports -l .)"
	cd $(GO_DIR) && $(GO) vet ./...
	cd $(GO_DIR) && $(GO) tool staticcheck ./...
	$(SHFMT) -d $(SHELL_FILES)
	$(SHELLCHECK) -s bash $(SHELL_FILES)
	$(CLANG_FORMAT) --dry-run --Werror $(C_FILE)
	$(MAKE) -C system/tcpfp/ebpf CLANG=$(CLANG) analyze
	$(CADDY) fmt system/caddy/Caddyfile.example | diff -u system/caddy/Caddyfile.example -
	$(CADDY) adapt --config system/caddy/Caddyfile.example --adapter caddyfile >/dev/null
	$(NPM) exec prettier -- --check .

typecheck:
	$(UV) run basedpyright

build:
	@mkdir -p build
	cd $(GO_DIR) && GOOS=linux GOARCH=amd64 CGO_ENABLED=0 $(GO) build -o ../../../build/mirage-syn ./cmd/mirage-syn
	$(MAKE) -C system/tcpfp/ebpf CLANG=$(CLANG) OUTPUT=../../../build/syn_rewrite.o
	PYTHONPYCACHEPREFIX=build/pycache $(UV) run python -m compileall -q system/tcpfp src/vps_ops

test:
	$(UV) run pytest
	cd $(GO_DIR) && $(GO) test ./...

check: lint typecheck build test
