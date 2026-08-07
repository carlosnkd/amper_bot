// Package config loads, validates and exposes the application configuration.
//
// Configuration is resolved from three layers, in increasing order of
// precedence:
//
//  1. Built-in defaults (see Default).
//  2. The JSON config file (config.json by default, see config.example.json).
//  3. Environment variables (SCREAMING_SNAKE_CASE, e.g. RATE_LIMIT_ENABLED).
//
// Every value is validated at startup so that a misconfigured deployment
// fails fast with an error naming the offending key.
package config

import (
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

// Defaults for every configuration key.
const (
	DefaultServerHost         = "0.0.0.0"
	DefaultServerPort         = 8080
	DefaultServerReadTimeout  = 15 * time.Second
	DefaultDatabaseURL        = "postgres://localhost:5432/app?sslmode=disable"
	DefaultDatabaseMaxOpen    = 10
	DefaultLogLevel           = "info"
	DefaultRateLimitEnabled   = false
	DefaultRateLimitRequests  = 100
	DefaultRateLimitWindow    = time.Minute
	DefaultConfigFilePath     = "config.json"
	configFilePathEnvVariable = "APP_CONFIG_FILE"
)

// Config is the fully parsed, validated application configuration.
type Config struct {
	Server   ServerConfig
	Database DatabaseConfig
	Log      LogConfig

	// RateLimit holds the global rate-limit policy. The values are parsed
	// and validated here, but no limiter enforces them yet; enforcement
	// arrives in a follow-up change.
	RateLimit RateLimitConfig
}

// ServerConfig holds HTTP server settings.
type ServerConfig struct {
	Host        string
	Port        int
	ReadTimeout time.Duration
}

// DatabaseConfig holds database connection settings.
type DatabaseConfig struct {
	URL          string
	MaxOpenConns int
}

// LogConfig holds logging settings.
type LogConfig struct {
	Level string
}

// RateLimitConfig is the typed, pre-parsed global rate-limit policy.
//
// A future limiter reads this struct directly; it never has to re-parse
// strings or durations.
type RateLimitConfig struct {
	// Enabled turns rate limiting on. Defaults to false so that adding
	// this section changes no existing behaviour.
	Enabled bool

	// Requests is the maximum number of requests allowed per Window.
	// Always a positive integer after validation.
	Requests int

	// Window is the length of the sliding/fixed window the Requests
	// budget applies to. Always non-zero and positive after validation.
	Window time.Duration
}

// PerSecond returns the configured budget expressed as a request rate.
// It is a convenience for the future limiter; Window is guaranteed
// non-zero by validation.
func (r RateLimitConfig) PerSecond() float64 {
	if r.Window <= 0 {
		return 0
	}
	return float64(r.Requests) / r.Window.Seconds()
}

// String renders the policy for startup logging.
func (r RateLimitConfig) String() string {
	if !r.Enabled {
		return "rate_limit: disabled"
	}
	return fmt.Sprintf("rate_limit: %d requests per %s (not yet enforced)", r.Requests, r.Window)
}

// --- raw (on-disk) representation -------------------------------------------------

type rawConfig struct {
	Server    *rawServer    `json:"server"`
	Database  *rawDatabase  `json:"database"`
	Log       *rawLog       `json:"log"`
	RateLimit *rawRateLimit `json:"rate_limit"`
}

type rawServer struct {
	Host        *string `json:"host"`
	Port        *int    `json:"port"`
	ReadTimeout *string `json:"read_timeout"`
}

type rawDatabase struct {
	URL          *string `json:"url"`
	MaxOpenConns *int    `json:"max_open_conns"`
}

type rawLog struct {
	Level *string `json:"level"`
}

type rawRateLimit struct {
	Enabled  *bool   `json:"enabled"`
	Requests *int    `json:"requests"`
	Window   *string `json:"window"`
}

// --- loading ----------------------------------------------------------------------

// Default returns the configuration used when nothing else is supplied.
func Default() Config {
	return Config{
		Server: ServerConfig{
			Host:        DefaultServerHost,
			Port:        DefaultServerPort,
			ReadTimeout: DefaultServerReadTimeout,
		},
		Database: DatabaseConfig{
			URL:          DefaultDatabaseURL,
			MaxOpenConns: DefaultDatabaseMaxOpen,
		},
		Log: LogConfig{
			Level: DefaultLogLevel,
		},
		RateLimit: RateLimitConfig{
			Enabled:  DefaultRateLimitEnabled,
			Requests: DefaultRateLimitRequests,
			Window:   DefaultRateLimitWindow,
		},
	}
}

// Load resolves defaults, the config file at path and environment
// overrides, then validates the result.
//
// If path is empty, APP_CONFIG_FILE is consulted, falling back to
// config.json. A missing file at the default location is not an error
// (defaults + env vars are enough to boot); a missing file at an
// explicitly requested location is.
func Load(path string) (*Config, error) {
	cfg := Default()

	explicit := path != ""
	if !explicit {
		if envPath := os.Getenv(configFilePathEnvVariable); envPath != "" {
			path, explicit = envPath, true
		} else {
			path = DefaultConfigFilePath
		}
	}

	if err := applyFile(&cfg, path, explicit); err != nil {
		return nil, err
	}
	if err := applyEnv(&cfg); err != nil {
		return nil, err
	}
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	return &cfg, nil
}

func applyFile(cfg *Config, path string, explicit bool) error {
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) && !explicit {
			return nil
		}
		return fmt.Errorf("config: cannot read config file %q: %w", path, err)
	}

	var raw rawConfig
	if err := json.Unmarshal(data, &raw); err != nil {
		return fmt.Errorf("config: cannot parse config file %q: %w", path, err)
	}

	if raw.Server != nil {
		if raw.Server.Host != nil {
			cfg.Server.Host = *raw.Server.Host
		}
		if raw.Server.Port != nil {
			cfg.Server.Port = *raw.Server.Port
		}
		if raw.Server.ReadTimeout != nil {
			d, err := parseDuration("server.read_timeout", "SERVER_READ_TIMEOUT", *raw.Server.ReadTimeout)
			if err != nil {
				return err
			}
			cfg.Server.ReadTimeout = d
		}
	}

	if raw.Database != nil {
		if raw.Database.URL != nil {
			cfg.Database.URL = *raw.Database.URL
		}
		if raw.Database.MaxOpenConns != nil {
			cfg.Database.MaxOpenConns = *raw.Database.MaxOpenConns
		}
	}

	if raw.Log != nil && raw.Log.Level != nil {
		cfg.Log.Level = *raw.Log.Level
	}

	if raw.RateLimit != nil {
		if raw.RateLimit.Enabled != nil {
			cfg.RateLimit.Enabled = *raw.RateLimit.Enabled
		}
		if raw.RateLimit.Requests != nil {
			cfg.RateLimit.Requests = *raw.RateLimit.Requests
		}
		if raw.RateLimit.Window != nil {
			d, err := parseDuration("rate_limit.window", "RATE_LIMIT_WINDOW", *raw.RateLimit.Window)
			if err != nil {
				return err
			}
			cfg.RateLimit.Window = d
		}
	}

	return nil
}

func applyEnv(cfg *Config) error {
	if v, ok := lookupEnv("SERVER_HOST"); ok {
		cfg.Server.Host = v
	}
	if v, ok := lookupEnv("SERVER_PORT"); ok {
		n, err := parseInt("server.port", "SERVER_PORT", v)
		if err != nil {
			return err
		}
		cfg.Server.Port = n
	}
	if v, ok := lookupEnv("SERVER_READ_TIMEOUT"); ok {
		d, err := parseDuration("server.read_timeout", "SERVER_READ_TIMEOUT", v)
		if err != nil {
			return err
		}
		cfg.Server.ReadTimeout = d
	}
	if v, ok := lookupEnv("DATABASE_URL"); ok {
		cfg.Database.URL = v
	}
	if v, ok := lookupEnv("DATABASE_MAX_OPEN_CONNS"); ok {
		n, err := parseInt("database.max_open_conns", "DATABASE_MAX_OPEN_CONNS", v)
		if err != nil {
			return err
		}
		cfg.Database.MaxOpenConns = n
	}
	if v, ok := lookupEnv("LOG_LEVEL"); ok {
		cfg.Log.Level = v
	}

	// Rate limit overrides.
	if v, ok := lookupEnv("RATE_LIMIT_ENABLED"); ok {
		b, err := parseBool("rate_limit.enabled", "RATE_LIMIT_ENABLED", v)
		if err != nil {
			return err
		}
		cfg.RateLimit.Enabled = b
	}
	if v, ok := lookupEnv("RATE_LIMIT_REQUESTS"); ok {
		n, err := parseInt("rate_limit.requests", "RATE_LIMIT_REQUESTS", v)
		if err != nil {
			return err
		}
		cfg.RateLimit.Requests = n
	}
	if v, ok := lookupEnv("RATE_LIMIT_WINDOW"); ok {
		d, err := parseDuration("rate_limit.window", "RATE_LIMIT_WINDOW", v)
		if err != nil {
			return err
		}
		cfg.RateLimit.Window = d
	}

	return nil
}

// --- validation -------------------------------------------------------------------

// Validate checks every configuration value, returning an error that
// names the offending key (and its environment-variable override) on the
// first problem found.
func (c *Config) Validate() error {
	if c.Server.Port <= 0 || c.Server.Port > 65535 {
		return invalid("server.port", "SERVER_PORT", c.Server.Port, "must be between 1 and 65535")
	}
	if c.Server.ReadTimeout <= 0 {
		return invalid("server.read_timeout", "SERVER_READ_TIMEOUT", c.Server.ReadTimeout, "must be a non-zero, positive duration (e.g. \"15s\")")
	}
	if strings.TrimSpace(c.Database.URL) == "" {
		return invalid("database.url", "DATABASE_URL", c.Database.URL, "must not be empty")
	}
	if c.Database.MaxOpenConns <= 0 {
		return invalid("database.max_open_conns", "DATABASE_MAX_OPEN_CONNS", c.Database.MaxOpenConns, "must be a positive integer")
	}
	switch strings.ToLower(strings.TrimSpace(c.Log.Level)) {
	case "debug", "info", "warn", "error":
	default:
		return invalid("log.level", "LOG_LEVEL", c.Log.Level, "must be one of: debug, info, warn, error")
	}

	return c.RateLimit.Validate()
}

// Validate checks the rate-limit section. The limits are validated even
// when the section is disabled so that flipping `enabled` on later can
// never fail at runtime on a value that was wrong all along.
func (r RateLimitConfig) Validate() error {
	if r.Requests <= 0 {
		return invalid("rate_limit.requests", "RATE_LIMIT_REQUESTS", r.Requests, "must be a positive integer")
	}
	if r.Window <= 0 {
		return invalid("rate_limit.window", "RATE_LIMIT_WINDOW", r.Window, "must be a non-zero, positive duration (e.g. \"1m\")")
	}
	return nil
}

// --- helpers ----------------------------------------------------------------------

func lookupEnv(key string) (string, bool) {
	v, ok := os.LookupEnv(key)
	if !ok {
		return "", false
	}
	v = strings.TrimSpace(v)
	if v == "" {
		return "", false
	}
	return v, true
}

func parseInt(key, envVar, value string) (int, error) {
	n, err := strconv.Atoi(strings.TrimSpace(value))
	if err != nil {
		return 0, invalid(key, envVar, value, "must be an integer")
	}
	return n, nil
}

func parseBool(key, envVar, value string) (bool, error) {
	b, err := strconv.ParseBool(strings.TrimSpace(value))
	if err != nil {
		return false, invalid(key, envVar, value, "must be a boolean (true/false)")
	}
	return b, nil
}

func parseDuration(key, envVar, value string) (time.Duration, error) {
	d, err := time.ParseDuration(strings.TrimSpace(value))
	if err != nil {
		return 0, invalid(key, envVar, value, "must be a duration such as \"500ms\", \"30s\" or \"1m\"")
	}
	return d, nil
}

func invalid(key, envVar string, value any, reason string) error {
	return fmt.Errorf("config: invalid value for %q (env %s): %v: %s", key, envVar, value, reason)
}
