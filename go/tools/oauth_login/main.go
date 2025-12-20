package main

import (
	"bufio"
	"context"
	"flag"
	"fmt"
	"net/url"
	"os"
	"strings"
	"time"

	"atlassian/atlassian"
)

func main() {
	clientID := flag.String("client-id", os.Getenv("ATLASSIAN_CLIENT_ID"), "Atlassian OAuth client ID")
	clientSecret := flag.String("client-secret", os.Getenv("ATLASSIAN_CLIENT_SECRET"), "Atlassian OAuth client secret")
	redirectURI := flag.String("redirect-uri", getenvDefault("ATLASSIAN_OAUTH_REDIRECT_URI", "http://localhost:8080/callback"), "OAuth redirect URI")
	scopesRaw := flag.String("scopes", os.Getenv("ATLASSIAN_OAUTH_SCOPES"), "Space- or comma-separated scopes")
	state := flag.String("state", os.Getenv("ATLASSIAN_OAUTH_STATE"), "Optional state")
	printResources := flag.Bool("print-accessible-resources", false, "Print accessible cloud IDs after login")
	flag.Parse()

	scopes := splitScopes(*scopesRaw)
	if strings.TrimSpace(*clientID) == "" || strings.TrimSpace(*clientSecret) == "" || len(scopes) == 0 {
		fmt.Fprintln(os.Stderr, "Missing required inputs. Provide -client-id, -client-secret, and -scopes (or set ATLASSIAN_CLIENT_ID, ATLASSIAN_CLIENT_SECRET, ATLASSIAN_OAUTH_SCOPES).")
		os.Exit(2)
	}

	authorizeURL, err := atlassian.BuildAuthorizeURL(*clientID, *redirectURI, scopes, *state)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	fmt.Println("Open this URL in your browser and complete consent:")
	fmt.Println(authorizeURL)
	fmt.Fprintln(os.Stderr, "")
	fmt.Fprintln(os.Stderr, "Paste the redirected URL (or just the `code` value):")

	code, err := readCodeFromStdin()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	token, err := atlassian.ExchangeAuthorizationCode(
		ctx,
		*clientID,
		*clientSecret,
		code,
		*redirectURI,
		atlassian.OAuthTokenRequestOptions{Timeout: 30 * time.Second},
	)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}

	fmt.Println("")
	fmt.Println("# Use these in your shell or .env (do NOT commit secrets):")
	fmt.Println("ATLASSIAN_OAUTH_ACCESS_TOKEN=" + token.AccessToken)
	if strings.TrimSpace(token.RefreshToken) != "" {
		fmt.Println("ATLASSIAN_OAUTH_REFRESH_TOKEN=" + strings.TrimSpace(token.RefreshToken))
	} else {
		fmt.Println("# No refresh_token returned; include offline_access scope and ensure your app is configured for refresh tokens.")
	}

	if *printResources {
		resources, err := atlassian.FetchAccessibleResources(
			ctx,
			token.AccessToken,
			atlassian.AccessibleResourcesOptions{Timeout: 30 * time.Second},
		)
		if err != nil {
			fmt.Fprintln(os.Stderr, "Failed to fetch accessible resources:", err)
			return
		}
		fmt.Println("")
		fmt.Println("# Accessible resources (cloud IDs):")
		for _, r := range resources {
			if strings.TrimSpace(r.ID) != "" && strings.TrimSpace(r.Name) != "" && strings.TrimSpace(r.URL) != "" {
				scopes := ""
				if len(r.Scopes) > 0 {
					scopes = " scopes=" + strings.Join(r.Scopes, ",")
				}
				fmt.Printf("- %s: id=%s url=%s%s\n", r.Name, r.ID, r.URL, scopes)
			}
		}
	}
}

func getenvDefault(key string, fallback string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return fallback
}

func splitScopes(raw string) []string {
	cleaned := strings.ReplaceAll(raw, ",", " ")
	fields := strings.Fields(cleaned)
	var out []string
	for _, f := range fields {
		if s := strings.TrimSpace(f); s != "" {
			out = append(out, s)
		}
	}
	return out
}

func readCodeFromStdin() (string, error) {
	reader := bufio.NewReader(os.Stdin)
	line, err := reader.ReadString('\n')
	if err != nil && strings.TrimSpace(line) == "" {
		return "", fmt.Errorf("failed to read input: %w", err)
	}
	raw := strings.TrimSpace(line)
	if raw == "" {
		return "", fmt.Errorf("missing code/redirected URL input")
	}
	if !strings.Contains(raw, "://") {
		return raw, nil
	}
	u, err := url.Parse(raw)
	if err != nil {
		return "", fmt.Errorf("invalid redirected URL: %w", err)
	}
	code := u.Query().Get("code")
	if strings.TrimSpace(code) == "" {
		return "", fmt.Errorf("redirected URL missing ?code=")
	}
	return strings.TrimSpace(code), nil
}
