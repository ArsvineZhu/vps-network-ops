package syn

import (
	"fmt"
	"os"
	"regexp"
	"time"

	"go.yaml.in/yaml/v4"
)

type SynConfig struct {
	Enabled        bool   `yaml:"enabled"`
	QueueNum       uint16 `yaml:"queue_num"`
	Profile        string `yaml:"profile"`
	FailureMode    string `yaml:"failure_mode"`
	StatusInterval string `yaml:"status_interval"`
}

// Deployment-owned firewall rules scope each queue to its traffic path.
// The daemon never installs or removes firewall rules.
type Config struct {
	Interface string    `yaml:"interface"`
	SYN       SynConfig `yaml:"syn"`
}

func LoadConfig(path string) (Config, error) {
	var c Config
	b, err := os.ReadFile(path)
	if err != nil {
		return c, err
	}
	if err = yaml.Load(b, &c, yaml.WithKnownFields()); err != nil {
		return c, err
	}
	return c, c.Validate()
}

func (c Config) Profile() (Profile, error) {
	switch c.SYN.Profile {
	case "windows":
		return Windows(), nil
	case "ios":
		return IOS(), nil
	default:
		return Profile{}, fmt.Errorf("syn.profile must be windows or ios")
	}
}

func (c Config) Validate() error {
	if !regexp.MustCompile(`^[A-Za-z0-9_.-]{1,15}$`).MatchString(c.Interface) {
		return fmt.Errorf("invalid interface name")
	}
	if _, err := c.Profile(); err != nil {
		return err
	}
	if c.SYN.FailureMode != "strict" && c.SYN.FailureMode != "open" {
		return fmt.Errorf("syn.failure_mode must be strict or open")
	}
	interval, err := time.ParseDuration(c.SYN.StatusInterval)
	if err != nil || interval < time.Second || interval > time.Hour {
		return fmt.Errorf("syn.status_interval must be between 1s and 1h")
	}
	return nil
}
