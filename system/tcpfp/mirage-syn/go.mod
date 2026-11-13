module github.com/ArsvineZhu/vps-network-ops/system/tcpfp/mirage-syn

go 1.26.0

require (
	github.com/florianl/go-nfqueue/v2 v2.1.0
	go.yaml.in/yaml/v4 v4.0.0
	golang.org/x/sys v0.50.0
)

require (
	github.com/BurntSushi/toml v1.4.1-0.20240526193622-a339e1f7089c // indirect
	github.com/google/go-cmp v0.7.0 // indirect
	github.com/mdlayher/netlink v1.11.2 // indirect
	github.com/mdlayher/socket v0.8.0 // indirect
	golang.org/x/exp/typeparams v0.0.0-20231108232855-2478ac86f678 // indirect
	golang.org/x/mod v0.42.0 // indirect
	golang.org/x/net v0.62.0 // indirect
	golang.org/x/sync v0.25.0 // indirect
	golang.org/x/telemetry v0.0.0-20261009151841-97e8ea77aa2a // indirect
	golang.org/x/tools v0.52.0 // indirect
	honnef.co/go/tools v0.8.2 // indirect
)

tool (
	golang.org/x/tools/cmd/goimports
	honnef.co/go/tools/cmd/staticcheck
)
