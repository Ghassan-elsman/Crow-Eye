# Build Configuration for EYE React Applications

## Overview

This document describes the Vite build configuration for the EYE Forensic Assistant React applications. The build produces two separate entry points optimized for PyQt5 QWebEngineView integration:

1. **Chat Interface** (`index.html`) - Main conversational AI interface
2. **Report Builder** (`report.html`) - Interactive report editing interface

## Build Output Structure

```
dist/
├── index.html              # Chat interface entry point
├── report.html             # Report builder entry point
├── favicon.svg             # Application icon
├── icons.svg               # SVG icon sprite
├── chat/
│   └── index.js           # Chat interface JavaScript bundle
├── report/
│   └── index.js           # Report builder JavaScript bundle
└── shared/
    ├── bridge.[hash].js   # Shared QWebChannel bridge code
    ├── bridge.[hash].css  # Bridge component styles
    ├── chat.[hash].css    # Chat interface styles
    └── report.[hash].css  # Report builder styles
```

## Build Scripts

### Production Build

```bash
npm run build
```

Builds both chat and report interfaces for production. Output is placed in `dist/` directory.

### Development Server

```bash
# Start dev server (defaults to chat interface)
npm run dev

# Start dev server with chat interface
npm run dev:chat

# Start dev server with report builder
npm run dev:report
```

### Preview Production Build

```bash
# Preview chat interface
npm run preview:chat

# Preview report builder
npm run preview:report
```

## Configuration Details

### Vite Configuration (`vite.config.ts`)

Key configuration settings:

1. **Multiple Entry Points**: Configured via `rollupOptions.input` to build both chat and report interfaces
2. **Base Path**: Set to `'./'` for relative paths (required for PyQt5 QWebEngineView)
3. **Asset Organization**: 
   - JavaScript bundles organized by entry point (`chat/`, `report/`)
   - Shared code in `shared/` directory
   - CSS files organized by component
4. **Build Optimization**:
   - Minification via esbuild
   - CSS code splitting enabled
   - Target: ES2015 for broad compatibility
   - No source maps in production

### TypeScript Configuration

- **tsconfig.app.json**: Excludes test files from build (`*.test.tsx`, `*.test.ts`, `src/test/`)
- **tsconfig.json**: Main TypeScript configuration
- **tsconfig.node.json**: Configuration for Vite config files

## PyQt5 Integration

The build output is designed for integration with PyQt5 QWebEngineView:

1. **Relative Paths**: All asset references use relative paths (`./`)
2. **QWebChannel**: HTML files include the QWebChannel script tag:
   ```html
   <script type="text/javascript" src="qrc:///qtwebchannel/qwebchannel.js"></script>
   ```
3. **Self-Contained**: All assets are bundled and referenced correctly
4. **Separate Interfaces**: Chat and report builder can be loaded independently

### Loading in PyQt5

```python
# Chat Interface
chat_view = QWebEngineView()
chat_view.load(QUrl.fromLocalFile(os.path.join(dist_path, 'index.html')))

# Report Builder
report_view = QWebEngineView()
report_view.load(QUrl.fromLocalFile(os.path.join(dist_path, 'report.html')))
```

## Dependencies

### Production Dependencies
- `react` - UI framework
- `react-dom` - React DOM rendering
- `react-markdown` - Markdown rendering
- `datatables.net` - Interactive data tables
- `@dnd-kit/core` & `@dnd-kit/sortable` - Drag-and-drop functionality

### Development Dependencies
- `vite` - Build tool
- `@vitejs/plugin-react` - React plugin for Vite
- `typescript` - Type checking
- `esbuild` - JavaScript minification
- `vitest` - Testing framework
- `@testing-library/react` - React testing utilities

## Testing

```bash
# Run tests once
npm run test

# Run tests in watch mode
npm run test:watch

# Run tests with UI
npm run test:ui
```

## Troubleshooting

### Build Fails with TypeScript Errors

Ensure test files are excluded in `tsconfig.app.json`:
```json
{
  "exclude": ["src/**/*.test.tsx", "src/**/*.test.ts", "src/test"]
}
```

### Assets Not Loading in PyQt5

1. Verify `base: './'` is set in `vite.config.ts`
2. Check that HTML files use relative paths (`./`)
3. Ensure QWebEngineView loads from local file path

### Missing esbuild Error

Install esbuild as a dev dependency:
```bash
npm install --save-dev esbuild
```

## Future Enhancements

- [ ] Add source maps for debugging (optional flag)
- [ ] Implement code splitting for larger bundles
- [ ] Add bundle size analysis
- [ ] Configure PWA support for offline capability
- [ ] Add compression (gzip/brotli) for production assets
