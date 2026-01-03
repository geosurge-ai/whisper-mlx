/**
 * useLocalStorage - Persist state to localStorage
 *
 * Features:
 * - Type-safe serialization/deserialization
 * - Graceful fallback if localStorage unavailable
 * - SSR-safe (deferred hydration)
 */

import { useState, useEffect, useCallback } from 'react'

function isLocalStorageAvailable(): boolean {
  try {
    const test = '__storage_test__'
    window.localStorage.setItem(test, test)
    window.localStorage.removeItem(test)
    return true
  } catch {
    return false
  }
}

const storageAvailable = isLocalStorageAvailable()

export function useLocalStorage<T>(
  key: string,
  initialValue: T
): [T, (value: T | ((prev: T) => T)) => void] {
  // Initialize with stored value or default
  const [storedValue, setStoredValue] = useState<T>(() => {
    if (!storageAvailable) return initialValue

    try {
      const item = window.localStorage.getItem(key)
      return item ? (JSON.parse(item) as T) : initialValue
    } catch (error) {
      console.warn(`Error reading localStorage key "${key}":`, error)
      return initialValue
    }
  })

  // Update localStorage when state changes
  const setValue = useCallback((value: T | ((prev: T) => T)) => {
    setStoredValue((prev) => {
      const nextValue = value instanceof Function ? value(prev) : value

      if (storageAvailable) {
        try {
          window.localStorage.setItem(key, JSON.stringify(nextValue))
        } catch (error) {
          console.warn(`Error writing localStorage key "${key}":`, error)
        }
      }

      return nextValue
    })
  }, [key])

  // Sync across tabs
  useEffect(() => {
    if (!storageAvailable) return

    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === key && e.newValue !== null) {
        try {
          setStoredValue(JSON.parse(e.newValue) as T)
        } catch {
          // Ignore parse errors from other sources
        }
      }
    }

    window.addEventListener('storage', handleStorageChange)
    return () => window.removeEventListener('storage', handleStorageChange)
  }, [key])

  return [storedValue, setValue]
}

/**
 * Clear all app-related localStorage
 */
export function clearLocalStorage(): void {
  if (!storageAvailable) return

  const keysToRemove = [
    'qwen-profile',
    'qwen-history',
    'qwen-recent-commands',
    'qwen-sessions',
  ]

  keysToRemove.forEach(key => {
    try {
      window.localStorage.removeItem(key)
    } catch {
      // Ignore
    }
  })
}
