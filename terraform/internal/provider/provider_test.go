// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0

package provider

import (
	"os"
	"testing"

	"github.com/hashicorp/terraform-plugin-framework/types"
)

func TestGetConfigOrEnv(t *testing.T) {
	tests := []struct {
		name         string
		configValue  types.String
		envKey       string
		defaultValue string
		envValue     string
		want         string
	}{
		{
			name:         "config value takes precedence",
			configValue:  types.StringValue("from-config"),
			envKey:       "TEST_ENV_KEY",
			defaultValue: "default",
			envValue:     "from-env",
			want:         "from-config",
		},
		{
			name:         "env value when config is null",
			configValue:  types.StringNull(),
			envKey:       "TEST_ENV_KEY",
			defaultValue: "default",
			envValue:     "from-env",
			want:         "from-env",
		},
		{
			name:         "env value when config is unknown",
			configValue:  types.StringUnknown(),
			envKey:       "TEST_ENV_KEY",
			defaultValue: "default",
			envValue:     "from-env",
			want:         "from-env",
		},
		{
			name:         "default when no config and no env",
			configValue:  types.StringNull(),
			envKey:       "TEST_ENV_KEY_MISSING",
			defaultValue: "default",
			envValue:     "",
			want:         "default",
		},
		{
			name:         "default when config is empty string",
			configValue:  types.StringValue(""),
			envKey:       "TEST_ENV_KEY_EMPTY",
			defaultValue: "default",
			envValue:     "",
			want:         "default",
		},
		{
			name:         "config with whitespace is trimmed",
			configValue:  types.StringValue("  trimmed  "),
			envKey:       "TEST_ENV_KEY",
			defaultValue: "default",
			envValue:     "",
			want:         "trimmed",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Clean up env before test
			os.Unsetenv(tt.envKey)
			if tt.envValue != "" {
				os.Setenv(tt.envKey, tt.envValue)
				defer os.Unsetenv(tt.envKey)
			}

			got := getConfigOrEnv(tt.configValue, tt.envKey, tt.defaultValue)
			if got != tt.want {
				t.Errorf("getConfigOrEnv() = %q, want %q", got, tt.want)
			}
		})
	}
}

func TestGetConfigOrEnvMulti(t *testing.T) {
	tests := []struct {
		name         string
		configValue  types.String
		envKeys      []string
		defaultValue string
		envSetup     map[string]string
		want         string
	}{
		{
			name:         "config value takes precedence",
			configValue:  types.StringValue("from-config"),
			envKeys:      []string{"KEY1", "KEY2"},
			defaultValue: "default",
			envSetup:     map[string]string{"KEY1": "env1", "KEY2": "env2"},
			want:         "from-config",
		},
		{
			name:         "first env key found",
			configValue:  types.StringNull(),
			envKeys:      []string{"KEY1", "KEY2"},
			defaultValue: "default",
			envSetup:     map[string]string{"KEY1": "env1", "KEY2": "env2"},
			want:         "env1",
		},
		{
			name:         "second env key when first missing",
			configValue:  types.StringNull(),
			envKeys:      []string{"KEY1", "KEY2"},
			defaultValue: "default",
			envSetup:     map[string]string{"KEY2": "env2"},
			want:         "env2",
		},
		{
			name:         "default when no env keys set",
			configValue:  types.StringNull(),
			envKeys:      []string{"KEY1", "KEY2"},
			defaultValue: "default",
			envSetup:     map[string]string{},
			want:         "default",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Clean up env before test
			for _, key := range tt.envKeys {
				os.Unsetenv(key)
			}
			for key, value := range tt.envSetup {
				os.Setenv(key, value)
				defer os.Unsetenv(key)
			}

			got := getConfigOrEnvMulti(tt.configValue, tt.envKeys, tt.defaultValue)
			if got != tt.want {
				t.Errorf("getConfigOrEnvMulti() = %q, want %q", got, tt.want)
			}
		})
	}
}
