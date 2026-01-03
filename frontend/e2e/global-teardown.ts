/**
 * Global Teardown - Stop daemon after all tests
 */

async function globalTeardown(): Promise<void> {
  const pid = process.env.DAEMON_PID

  if (pid) {
    console.log(`\n[TEARDOWN] Stopping daemon (PID: ${pid})...`)
    try {
      process.kill(Number(pid), 'SIGTERM')

      // Give it a moment to shut down gracefully
      await new Promise(resolve => setTimeout(resolve, 1000))

      // Force kill if still running
      try {
        process.kill(Number(pid), 0) // Check if still running
        process.kill(Number(pid), 'SIGKILL')
        console.log('[TEARDOWN] Daemon force-killed')
      } catch {
        console.log('[TEARDOWN] Daemon stopped cleanly')
      }
    } catch (err) {
      console.log(`[TEARDOWN] Daemon already stopped or error: ${err}`)
    }
  } else {
    console.log('\n[TEARDOWN] No daemon PID found')
  }
}

export default globalTeardown
