// 路由 hook：订阅 router 模块的变化，返回当前 path 和 navigate 函数
import { useState, useEffect } from 'react'
import { getPath, navigate, subscribe } from '../lib/router.ts'

export function useRouter() {
  const [path, setPath] = useState(getPath)

  useEffect(() => {
    const update = () => setPath(getPath())
    const unsub = subscribe(update)
    window.addEventListener('popstate', update)
    return () => {
      unsub()
      window.removeEventListener('popstate', update)
    }
  }, [])

  return { path, navigate }
}
