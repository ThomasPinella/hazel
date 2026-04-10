#!/usr/bin/env node
/**
 * Hazel Canvas Dashboard Server
 *
 * Unified server for Entity Graph + Intents Dashboard + Memory Viewer
 * Serves the dashboard UI and provides live API for intents from SQLite
 *
 * Usage: node dashboard-server.js [port]
 * Default port: 8081
 *
 * Environment variables:
 *   HAZEL_WORKSPACE  — path to Hazel workspace (default: ~/.hazel/workspace)
 *   DASHBOARD_PORT     — server port (default: 8081)
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');
const { URL } = require('url');

// Load better-sqlite3
let Database;
try {
  Database = require('better-sqlite3');
} catch {
  console.error('Error: better-sqlite3 not found. Install with:');
  console.error('  cd canvas && npm install');
  process.exit(1);
}

// --- Configuration ---
const PORT = parseInt(process.env.DASHBOARD_PORT || process.argv[2]) || 8081;

// Resolve workspace: env var > CLI arg > Hazel config > default
function resolveWorkspace() {
  if (process.env.HAZEL_WORKSPACE) {
    return process.env.HAZEL_WORKSPACE.replace(/^~/, os.homedir());
  }

  // Try reading Hazel config
  const configPath = path.join(os.homedir(), '.hazel', 'config.json');
  try {
    const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
    const ws = config?.agents?.defaults?.workspace
      || config?.agents?.defaults?.Workspace;
    if (ws) return ws.replace(/^~/, os.homedir());
  } catch { /* config not found or unreadable */ }

  return path.join(os.homedir(), '.hazel', 'workspace');
}

const WORKSPACE = resolveWorkspace();
const CANVAS_DIR = __dirname;
const DB_PATH = path.join(WORKSPACE, 'data', 'intents.db');

// MIME types
const MIME_TYPES = {
  '.html': 'text/html',
  '.js': 'application/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.jsonl': 'application/jsonl; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.md': 'text/markdown; charset=utf-8',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
};

// Open database (may not exist yet if no intents have been created)
let db = null;
try {
  if (fs.existsSync(DB_PATH)) {
    db = new Database(DB_PATH, { readonly: true });
    console.log('  Database:  ', DB_PATH);
  } else {
    console.log('  Database:   (not yet created — intents API will return empty)');
  }
} catch (err) {
  console.error('  Database:   FAILED -', err.message);
}

// --- API Handlers ---

function handleApiIntents(res, url) {
  if (!db) return sendJson(res, 200, { intents: [], count: 0 });

  const params = url.searchParams;

  let sql = `
    SELECT
      i.*,
      GROUP_CONCAT(DISTINCT il.entity_path) as linked_paths,
      GROUP_CONCAT(DISTINCT il.entity_id) as linked_ids
    FROM intents i
    LEFT JOIN intent_links il ON i.id = il.intent_id
    WHERE 1=1
  `;
  const args = [];

  // Filters
  const status = params.getAll('status');
  if (status.length > 0) {
    sql += ` AND i.status IN (${status.map(() => '?').join(',')})`;
    args.push(...status);
  }

  const type = params.getAll('type');
  if (type.length > 0) {
    sql += ` AND i.type IN (${type.map(() => '?').join(',')})`;
    args.push(...type);
  }

  const q = params.get('q');
  if (q) {
    sql += ` AND (i.title LIKE ? OR i.body LIKE ?)`;
    args.push(`%${q}%`, `%${q}%`);
  }

  const entityPath = params.get('entity_path');
  if (entityPath) {
    sql += ` AND il.entity_path = ?`;
    args.push(entityPath);
  }

  sql += ` GROUP BY i.id ORDER BY
    CASE i.status
      WHEN 'active' THEN 1
      WHEN 'snoozed' THEN 2
      ELSE 3
    END,
    COALESCE(i.due_at, i.start_at, '9999') ASC
  `;

  const limit = parseInt(params.get('limit')) || 200;
  const offset = parseInt(params.get('offset')) || 0;
  sql += ` LIMIT ? OFFSET ?`;
  args.push(limit, offset);

  try {
    const rows = db.prepare(sql).all(...args);

    // Parse linked paths/ids into arrays
    const intents = rows.map(row => ({
      ...row,
      linked_paths: row.linked_paths ? row.linked_paths.split(',') : [],
      linked_ids: row.linked_ids ? row.linked_ids.split(',') : [],
    }));

    sendJson(res, 200, { intents, count: intents.length });
  } catch (err) {
    sendJson(res, 500, { error: err.message });
  }
}

function handleApiIntent(res, id) {
  if (!db) return sendJson(res, 404, { error: 'No database' });

  try {
    const intent = db.prepare('SELECT * FROM intents WHERE id = ?').get(id);
    if (!intent) {
      sendJson(res, 404, { error: 'Intent not found' });
      return;
    }

    const links = db.prepare('SELECT * FROM intent_links WHERE intent_id = ?').all(id);
    sendJson(res, 200, { intent, links });
  } catch (err) {
    sendJson(res, 500, { error: err.message });
  }
}

function handleApiStats(res) {
  if (!db) return sendJson(res, 200, { stats: [], overdue: 0, upcoming: 0 });

  try {
    const stats = db.prepare(`
      SELECT
        status,
        type,
        COUNT(*) as count
      FROM intents
      GROUP BY status, type
    `).all();

    const overdue = db.prepare(`
      SELECT COUNT(*) as count
      FROM intents
      WHERE status = 'active'
        AND due_at IS NOT NULL
        AND due_at < datetime('now')
    `).get();

    const upcoming = db.prepare(`
      SELECT COUNT(*) as count
      FROM intents
      WHERE status = 'active'
        AND (due_at IS NOT NULL OR start_at IS NOT NULL)
        AND COALESCE(due_at, start_at) BETWEEN datetime('now') AND datetime('now', '+7 days')
    `).get();

    sendJson(res, 200, {
      stats,
      overdue: overdue?.count || 0,
      upcoming: upcoming?.count || 0
    });
  } catch (err) {
    sendJson(res, 500, { error: err.message });
  }
}

function handleApiMemoryDaily(res) {
  try {
    const memoryDir = path.join(WORKSPACE, 'memory');
    if (!fs.existsSync(memoryDir)) {
      sendJson(res, 200, { dates: [] });
      return;
    }
    const files = fs.readdirSync(memoryDir)
      .filter(f => /^\d{4}-\d{2}-\d{2}\.md$/.test(f))
      .map(f => f.replace('.md', ''))
      .sort()
      .reverse();
    sendJson(res, 200, { dates: files });
  } catch (err) {
    sendJson(res, 500, { error: err.message });
  }
}

function handleApiChanges(res, url) {
  const params = url.searchParams;
  const changesPath = path.join(WORKSPACE, 'memory', '_index', 'changes.jsonl');

  try {
    if (!fs.existsSync(changesPath)) {
      sendJson(res, 200, { changes: [], count: 0 });
      return;
    }

    const lines = fs.readFileSync(changesPath, 'utf-8')
      .split('\n')
      .filter(l => l.trim())
      .map(l => { try { return JSON.parse(l); } catch { return null; } })
      .filter(Boolean);

    let filtered = lines;

    const since = params.get('since');
    if (since) filtered = filtered.filter(c => c.ts >= since);

    const until = params.get('until');
    if (until) filtered = filtered.filter(c => c.ts <= until);

    const entityId = params.get('entity_id');
    if (entityId) filtered = filtered.filter(c => c.entity_id === entityId);

    const entityType = params.get('entity_type');
    if (entityType) filtered = filtered.filter(c => c.entity_type === entityType);

    const limit = parseInt(params.get('limit')) || 100;
    filtered = filtered.slice(-limit).reverse();

    sendJson(res, 200, { changes: filtered, count: filtered.length });
  } catch (err) {
    sendJson(res, 500, { error: err.message });
  }
}

// --- Response Helpers ---

function sendJson(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}

// --- Static File Handler ---

function serveFile(res, filePath) {
  fs.readFile(filePath, (err, data) => {
    if (err) {
      if (err.code === 'ENOENT') {
        res.writeHead(404);
        res.end('Not found');
      } else {
        res.writeHead(500);
        res.end('Server error');
      }
      return;
    }

    const ext = path.extname(filePath).toLowerCase();
    const contentType = MIME_TYPES[ext] || 'application/octet-stream';
    res.writeHead(200, { 'Content-Type': contentType });
    res.end(data);
  });
}

function serveWorkspaceFile(res, relativePath) {
  // Security: resolve and check it's within workspace
  const fullPath = path.resolve(WORKSPACE, relativePath);
  if (!fullPath.startsWith(path.resolve(WORKSPACE))) {
    res.writeHead(403);
    res.end('Forbidden');
    return;
  }
  serveFile(res, fullPath);
}

// --- Main Request Handler ---

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const pathname = url.pathname;

  // CORS headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  // Dashboard HTML (served from canvas dir)
  if (pathname === '/' || pathname === '/dashboard.html') {
    return serveFile(res, path.join(CANVAS_DIR, 'dashboard.html'));
  }

  // API routes
  if (pathname === '/api/intents') {
    return handleApiIntents(res, url);
  }

  if (pathname.startsWith('/api/intents/')) {
    const id = pathname.split('/')[3];
    return handleApiIntent(res, id);
  }

  if (pathname === '/api/stats') {
    return handleApiStats(res);
  }

  if (pathname === '/api/memory/daily') {
    return handleApiMemoryDaily(res);
  }

  if (pathname === '/api/changes') {
    return handleApiChanges(res, url);
  }

  // Health check
  if (pathname === '/health') {
    sendJson(res, 200, {
      status: 'ok',
      uptime: process.uptime(),
      workspace: WORKSPACE,
      database: db ? 'connected' : 'not available'
    });
    return;
  }

  // Workspace files (memory/*, data/*, etc.)
  if (pathname.startsWith('/memory/') || pathname.startsWith('/data/')) {
    const relativePath = pathname.slice(1); // strip leading /
    return serveWorkspaceFile(res, relativePath);
  }

  // Fallback: try workspace root files (MEMORY.md, etc.)
  if (pathname.endsWith('.md') || pathname.endsWith('.jsonl')) {
    const relativePath = pathname.slice(1);
    return serveWorkspaceFile(res, relativePath);
  }

  // Static assets from canvas dir
  const canvasAsset = path.join(CANVAS_DIR, pathname);
  if (fs.existsSync(canvasAsset) && fs.statSync(canvasAsset).isFile()) {
    return serveFile(res, canvasAsset);
  }

  res.writeHead(404);
  res.end('Not found');
});

server.listen(PORT, '127.0.0.1', () => {
  console.log('');
  console.log('Hazel Canvas Dashboard');
  console.log('\u2500'.repeat(40));
  console.log(`   Local:     http://localhost:${PORT}`);
  console.log(`   Workspace: ${WORKSPACE}`);
  console.log('');
  console.log('   Dashboard: /');
  console.log('   API:       /api/intents, /api/stats, /api/changes');
  console.log('   Health:    /health');
  console.log('\u2500'.repeat(40));
});

// Graceful shutdown
function shutdown() {
  console.log('\nShutting down...');
  if (db) db.close();
  server.close(() => {
    console.log('Server closed.');
    process.exit(0);
  });
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
