import { useState, useEffect } from 'react'

function useTheme() {
  const [isDark, setIsDark] = useState(() => {
    const saved = localStorage.getItem('xcash-theme')
    return saved !== null ? saved === 'dark' : true // default dark
  })

  useEffect(() => {
    const html = document.documentElement
    if (isDark) {
      html.classList.add('dark')
    } else {
      html.classList.remove('dark')
    }
    localStorage.setItem('xcash-theme', isDark ? 'dark' : 'light')
  }, [isDark])

  const toggleTheme = () => setIsDark(prev => !prev)

  return { isDark, toggleTheme }
}

export default useTheme
