//go:build integration
// +build integration

package integration

import (
	"bufio"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func loadDotEnvIfPresent(t *testing.T) {
	t.Helper()

	wd, err := os.Getwd()
	if err != nil {
		return
	}

	dir := wd
	for i := 0; i < 8; i++ {
		envPath := filepath.Join(dir, ".env")
		if _, err := os.Stat(envPath); err == nil {
			f, err := os.Open(envPath)
			if err != nil {
				return
			}
			defer f.Close()

			scanner := bufio.NewScanner(f)
			for scanner.Scan() {
				line := strings.TrimSpace(scanner.Text())
				if line == "" || strings.HasPrefix(line, "#") {
					continue
				}
				if strings.HasPrefix(line, "export ") {
					line = strings.TrimSpace(strings.TrimPrefix(line, "export "))
				}
				k, v, ok := strings.Cut(line, "=")
				if !ok {
					continue
				}
				key := strings.TrimSpace(k)
				if key == "" {
					continue
				}
				if _, exists := os.LookupEnv(key); exists {
					continue
				}
				value := strings.TrimSpace(v)
				if len(value) >= 2 {
					if (strings.HasPrefix(value, "\"") && strings.HasSuffix(value, "\"")) || (strings.HasPrefix(value, "'") && strings.HasSuffix(value, "'")) {
						value = value[1 : len(value)-1]
					}
				}
				_ = os.Setenv(key, value)
			}
			return
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return
		}
		dir = parent
	}
}

