/**
 * Global Setup - Start daemon before all tests
 */

import { spawn, ChildProcess } from 'child_process'
import { dirname, join } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

const DAEMON_PORT = 5997
const DAEMON_URL = `http://127.0.0.1:${DAEMON_PORT}`
const STARTUP_TIMEOUT = 60_000 // 60 seconds for model loading

let daemonProcess: ChildProcess | null = null

async function waitForDaemon(timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${DAEMON_URL}/health`, {
        signal: AbortSignal.timeout(2000),
      })
      if (response.ok) {
        return true
      }
    } catch {
      // Not ready yet
    }
    await new Promise(resolve => setTimeout(resolve, 500))
  }
  return false
}

async function globalSetup(): Promise<void> {
  console.log('\n[SETUP] Starting Qwen daemon...')

  const projectRoot = join(__dirname, '..', '..')
  const venvPython = join(projectRoot, '.venv', 'bin', 'python')

  // Mirror data directories (for tool tests)
  const homeDir = process.env.HOME || '/Users/sweater'
  const mirrorBase = join(homeDir, 'Github', 'vibe-os')

  // Start daemon process using venv's Python
  daemonProcess = spawn(
    venvPython,
    ['-m', 'daemon.server', '--host', '127.0.0.1', '--port', String(DAEMON_PORT)],
    {
      cwd: projectRoot,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...process.env,
        PYTHONPATH: projectRoot,
        // Ensure venv is used
        VIRTUAL_ENV: join(projectRoot, '.venv'),
        PATH: `${join(projectRoot, '.venv', 'bin')}:${process.env.PATH}`,
        // Mirror data directories for tool tests
        LINEAR_MIRROR_DIR: join(mirrorBase, 'linear_mirror'),
        VIBEOS_SLACK_MIRROR_DIR: join(mirrorBase, 'slack_mirror'),
      },
    }
  )

  // Store PID for teardown
  if (daemonProcess.pid) {
    process.env.DAEMON_PID = String(daemonProcess.pid)
    console.log(`[SETUP] Daemon PID: ${daemonProcess.pid}`)
  }

  // Log daemon output for debugging
  daemonProcess.stdout?.on('data', (data: Buffer) => {
    const line = data.toString().trim()
    if (line) console.log(`[DAEMON] ${line}`)
  })

  daemonProcess.stderr?.on('data', (data: Buffer) => {
    const line = data.toString().trim()
    if (line) console.log(`[DAEMON ERROR] ${line}`)
  })

  daemonProcess.on('error', (err) => {
    console.error(`[SETUP] Failed to start daemon: ${err.message}`)
  })

  daemonProcess.on('exit', (code) => {
    if (code !== null && code !== 0) {
      console.error(`[SETUP] Daemon exited with code ${code}`)
    }
  })

  // Wait for daemon to be ready
  console.log(`[SETUP] Waiting for daemon at ${DAEMON_URL}...`)
  const ready = await waitForDaemon(STARTUP_TIMEOUT)

  if (!ready) {
    daemonProcess.kill()
    throw new Error(`Daemon failed to start within ${STARTUP_TIMEOUT / 1000}s`)
  }

  console.log('[SETUP] Daemon is ready!\n')
}

export default globalSetup
