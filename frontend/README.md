# Qwen Daemon Frontend

A minimal, Bauhaus-inspired local-first UI for the Qwen Daemon API.

## Features

- **Command Palette** (⌘K) - Quick access to profiles, tools, and actions
- **Three-Panel Layout** - Profiles rail, chat canvas, tools panel
- **Local-First** - Profile selection, chat history, and palette history persist to localStorage
- **Bauhaus Design** - Bold color blocks, generous spacing, clean typography

## Prerequisites

- Node.js 18+ (provided via Nix)
- Running Qwen Daemon at `http://127.0.0.1:5997`

## Quick Start

```bash
# From project root
cd frontend

# Install dependencies (pnpm provided via Nix)
pnpm install

# Start dev server (proxies /api to daemon)
pnpm dev
```

Open http://localhost:8792

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start development server on port 8792 |
| `npm run build` | Build for production |
| `npm run preview` | Preview production build |
| `npm run typecheck` | Run TypeScript type checking |
| `npm run test:e2e` | Run E2E tests (headless) |
| `npm run test:e2e:headed` | Run E2E tests (visible browser) |
| `npm run test:e2e:ui` | Run E2E tests with Playwright UI |

## E2E Tests

E2E tests use [Playwright](https://playwright.dev/) and are located in `e2e/`.

```bash
# Run tests (daemon + frontend start automatically)
pnpm test:e2e

# Or use the convenience script from project root
../run-frontend-tests
```

## Architecture

```
frontend/
├── src/
│   ├── api/           # Typed API client for daemon endpoints
│   ├── components/    # React components (Layout, ChatView, CommandPalette, etc.)
│   ├── hooks/         # Custom hooks (useAppState, useLocalStorage, useFocusTrap)
│   ├── App.tsx        # Main application component
│   ├── main.tsx       # Entry point
│   ├── tokens.css     # Bauhaus design tokens (colors, spacing, typography)
│   └── index.css      # Global styles
├── index.html
├── package.json
├── tsconfig.json
└── vite.config.ts
```

## Daemon URL Configuration

By default, the frontend proxies API requests through Vite:
- Dev: `http://localhost:8792/api/*` → `http://127.0.0.1:5997/*`
- Prod: Configure your reverse proxy accordingly

To change the daemon URL, edit `vite.config.ts`:

```ts
proxy: {
  '/api': {
    target: 'http://YOUR_DAEMON_HOST:PORT',
    // ...
  },
},
```

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| ⌘K / Ctrl+K | Open command palette |
| ↑↓ | Navigate palette items |
| Enter | Select palette item |
| Escape | Close palette |
| Enter | Send message (in composer) |
| Shift+Enter | New line (in composer) |

## Design System

The UI follows Bauhaus principles:

- **Colors**: Primary red (#e63946), Secondary blue (#1d3557), Accent yellow (#f4a261)
- **Spacing**: 8px grid system (--space-1 through --space-24)
- **Typography**: Inter for UI, JetBrains Mono for code
- **Borders**: 2px solid, small radius (4-16px)

All design tokens are in `src/tokens.css`.
