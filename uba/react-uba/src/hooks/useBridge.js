/**
 * useBridge — wraps the QWebChannel bridge (window.bridge) with retry logic.
 * Mirrors the timeline hook. In a browser (dev) there is no bridge, so the
 * hook resolves to null and callBridge returns null.
 */
import { useCallback, useEffect, useState } from 'react'

let bridgePromise = null

function waitForBridge(attempt = 1) {
  const MAX_RETRIES = 3
  const TIMEOUT_MS = 10000
  const RETRY_DELAYS = [1000, 2000, 4000]
  if (bridgePromise) return bridgePromise

  bridgePromise = new Promise((resolve) => {
    if (window.bridge) {
      resolve(window.bridge)
      return
    }
    let timeoutId = null
    let resolved = false
    const handleTimeout = () => {
      if (resolved) return
      resolved = true
      if (attempt < MAX_RETRIES) {
        bridgePromise = null
        setTimeout(() => waitForBridge(attempt + 1).then(resolve), RETRY_DELAYS[attempt - 1])
      } else {
        resolve(null)
      }
    }
    timeoutId = setTimeout(handleTimeout, TIMEOUT_MS)
    const script = document.createElement('script')
    script.src = 'qrc:///qtwebchannel/qwebchannel.js'
    script.onload = () => {
      if (resolved) return
      try {
        if (window.QWebChannel && window.qt && window.qt.webChannelTransport) {
          new window.QWebChannel(window.qt.webChannelTransport, (channel) => {
            if (resolved) return
            resolved = true
            clearTimeout(timeoutId)
            window.bridge = channel.objects.bridge
            resolve(window.bridge)
          })
        } else {
          resolved = true
          clearTimeout(timeoutId)
          resolve(null)
        }
      } catch (e) {
        resolved = true
        clearTimeout(timeoutId)
        resolve(null)
      }
    }
    script.onerror = () => {
      if (resolved) return
      resolved = true
      clearTimeout(timeoutId)
      resolve(null)
    }
    document.head.appendChild(script)
  })
  return bridgePromise
}

export function useBridge() {
  const [bridge, setBridge] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isDev, setIsDev] = useState(false)

  useEffect(() => {
    waitForBridge().then((b) => {
      if (b) setBridge(b)
      else setIsDev(true)
      setIsLoading(false)
    })
  }, [])

  const callBridge = useCallback(async (method, ...args) => {
    if (!bridge) return null
    return new Promise((resolve, reject) => {
      try {
        const result = bridge[method](...args)
        if (typeof result === 'string') resolve(JSON.parse(result))
        else if (result && typeof result.then === 'function')
          result.then((r) => resolve(JSON.parse(r))).catch(reject)
        else resolve(result)
      } catch (e) {
        reject(e)
      }
    })
  }, [bridge])

  return { bridge, callBridge, isLoading, isDev }
}
