"""
Background scheduler for Google sync.

Runs continuous sync for all configured accounts.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime
from typing import Any

from .auth import list_accounts
from .calendar import sync_calendar
from .gmail import sync_gmail

logger = logging.getLogger("qwen.sync.scheduler")

# Configuration
SYNC_INTERVAL_SECONDS = 5 * 60  # 5 minutes
LOOKBACK_DAYS = 365  # 1 year

# Global state
_shutdown_event: asyncio.Event | None = None
_scheduler_task: asyncio.Task[None] | None = None
_scheduler_thread: threading.Thread | None = None


async def sync_account(account: str) -> dict[str, Any]:
    """
    Sync Gmail and Calendar for a single account.

    Runs synchronous sync operations in a thread pool.
    """
    logger.info(f"[Scheduler] Starting sync for account: {account}")

    results: dict[str, Any] = {
        "account": account,
        "started_at": datetime.utcnow().isoformat(),
    }

    loop = asyncio.get_event_loop()

    # Sync Gmail
    try:
        gmail_stats = await loop.run_in_executor(
            None, lambda: sync_gmail(account, lookback_days=LOOKBACK_DAYS)
        )
        results["gmail"] = gmail_stats
        logger.info(
            f"[{account}] Gmail: {gmail_stats.get('new_emails', 0)} new, "
            f"{gmail_stats.get('attachments', 0)} attachments"
        )
    except Exception as e:
        logger.error(f"[{account}] Gmail sync failed: {e}")
        results["gmail_error"] = str(e)

    # Sync Calendar
    try:
        calendar_stats = await loop.run_in_executor(
            None, lambda: sync_calendar(account, lookback_days=LOOKBACK_DAYS)
        )
        results["calendar"] = calendar_stats
        logger.info(
            f"[{account}] Calendar: {calendar_stats.get('new_events', 0)} new "
            f"from {calendar_stats.get('calendars_synced', 0)} calendars"
        )
    except Exception as e:
        logger.error(f"[{account}] Calendar sync failed: {e}")
        results["calendar_error"] = str(e)

    results["completed_at"] = datetime.utcnow().isoformat()
    return results


async def sync_all_accounts() -> list[dict[str, Any]]:
    """Sync all configured accounts sequentially."""
    accounts = list_accounts()

    if not accounts:
        logger.debug("[Scheduler] No accounts configured, skipping sync")
        return []

    logger.info(f"[Scheduler] Syncing {len(accounts)} account(s): {', '.join(accounts)}")

    results = []
    for account in accounts:
        try:
            result = await sync_account(account)
            results.append(result)
        except Exception as e:
            logger.error(f"[Scheduler] Account {account} sync failed: {e}")
            results.append({
                "account": account,
                "error": str(e),
            })

    return results


async def start_sync_scheduler() -> None:
    """
    Start the background sync scheduler.

    Runs forever until stop_sync_scheduler is called.
    """
    global _shutdown_event
    _shutdown_event = asyncio.Event()

    logger.info(
        f"[Scheduler] Started. Sync interval: {SYNC_INTERVAL_SECONDS}s, "
        f"Lookback: {LOOKBACK_DAYS} days"
    )

    # Initial sync on startup
    try:
        await sync_all_accounts()
    except Exception as e:
        logger.error(f"[Scheduler] Initial sync failed: {e}")

    # Continuous sync loop
    while not _shutdown_event.is_set():
        try:
            # Wait for interval or shutdown
            try:
                await asyncio.wait_for(
                    _shutdown_event.wait(),
                    timeout=SYNC_INTERVAL_SECONDS,
                )
                # If we get here, shutdown was requested
                break
            except asyncio.TimeoutError:
                # Normal timeout, proceed with sync
                pass

            # Run sync
            await sync_all_accounts()

        except Exception as e:
            logger.error(f"[Scheduler] Sync cycle failed: {e}")

    logger.info("[Scheduler] Stopped")


def stop_sync_scheduler(task: asyncio.Task[None]) -> None:
    """
    Stop the background sync scheduler.

    Args:
        task: The task returned by asyncio.create_task(start_sync_scheduler())
    """
    global _shutdown_event

    if _shutdown_event:
        _shutdown_event.set()

    if task and not task.done():
        task.cancel()
        try:
            # Give it a moment to clean up
            pass
        except Exception:
            pass


async def run_manual_sync(accounts: list[str] | None = None) -> list[dict[str, Any]]:
    """
    Run a manual sync for specific accounts or all accounts.

    Args:
        accounts: List of account names to sync, or None for all

    Returns:
        List of sync results
    """
    if accounts is None:
        return await sync_all_accounts()

    results = []
    for account in accounts:
        try:
            result = await sync_account(account)
            results.append(result)
        except Exception as e:
            logger.error(f"Manual sync failed for {account}: {e}")
            results.append({
                "account": account,
                "error": str(e),
            })

    return results


def _run_scheduler_in_thread() -> None:
    """Run the async scheduler in a dedicated thread with its own event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(start_sync_scheduler())
    except Exception as e:
        logger.error(f"Scheduler thread error: {e}")
    finally:
        loop.close()


def start_scheduler() -> None:
    """
    Start the Google sync scheduler in a background thread.

    This is the main entry point called by the daemon server.
    Runs the async scheduler in a separate thread so it doesn't block.
    """
    global _scheduler_thread

    accounts = list_accounts()
    if not accounts:
        logger.info("[Scheduler] No Google accounts configured. Skipping sync.")
        logger.info("[Scheduler] To add an account: python -m daemon.sync.auth --account NAME")
        return

    logger.info(f"[Scheduler] Starting background sync for {len(accounts)} account(s)")
    logger.info(f"[Scheduler] Accounts: {', '.join(accounts)}")
    logger.info(f"[Scheduler] Sync interval: {SYNC_INTERVAL_SECONDS}s, Lookback: {LOOKBACK_DAYS} days")

    _scheduler_thread = threading.Thread(
        target=_run_scheduler_in_thread,
        name="google-sync-scheduler",
        daemon=True,  # Dies when main thread exits
    )
    _scheduler_thread.start()


def stop_scheduler() -> None:
    """
    Stop the Google sync scheduler.

    Called during daemon shutdown.
    """
    global _shutdown_event, _scheduler_thread

    if _shutdown_event:
        _shutdown_event.set()
        logger.info("[Scheduler] Shutdown signal sent")

    if _scheduler_thread and _scheduler_thread.is_alive():
        _scheduler_thread.join(timeout=5)
        if _scheduler_thread.is_alive():
            logger.warning("[Scheduler] Thread did not stop gracefully")
