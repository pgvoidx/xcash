import { useState, useEffect } from "react"
import en from "@/locales/en.json"
import zh from "@/locales/zh.json"

const translations = {
  en,
  zh,
  "zh-CN": zh,
  "zh-TW": zh,
  "zh-HK": zh,
}

/**
 * 从浏览器获取语言偏好
 * @returns {string} 语言代码 ('en' 或 'zh')
 */
function getBrowserLanguage() {
  // 获取浏览器语言
  const browserLang = navigator.language || navigator.userLanguage || "en"

  // 简化语言代码（例如 'zh-CN' -> 'zh', 'en-US' -> 'en'）
  const langCode = browserLang.split("-")[0]

  // 如果是中文相关语言，返回 'zh'，否则默认返回 'en'
  return langCode === "zh" ? "zh" : "en"
}

/**
 * i18n Hook
 * 根据浏览器语言自动选择语言，默认英文
 */
export function useI18n() {
  const [locale, setLocale] = useState(() => getBrowserLanguage())

  useEffect(() => {
    // 监听语言变化（如果需要支持动态切换）
    const handleLanguageChange = () => {
      setLocale(getBrowserLanguage())
    }

    window.addEventListener("languagechange", handleLanguageChange)
    return () => window.removeEventListener("languagechange", handleLanguageChange)
  }, [])

  /**
   * 获取翻译文本
   * @param {string} key - 翻译键，支持嵌套路径如 'invoice.title'
   * @param {object} params - 可选的参数对象，用于替换占位符
   * @returns {string} 翻译后的文本
   */
  const t = (key, params = {}) => {
    const keys = key.split(".")
    let translation = translations[locale] || translations.en

    // 遍历键路径
    for (const k of keys) {
      translation = translation?.[k]
      if (!translation) break
    }

    // 如果找不到翻译，尝试使用英文
    if (!translation) {
      translation = translations.en
      for (const k of keys) {
        translation = translation?.[k]
        if (!translation) break
      }
    }

    // 如果还是找不到，返回键本身
    if (!translation) {
      return key
    }

    // 替换参数占位符 {{param}}
    if (typeof translation === "string" && Object.keys(params).length > 0) {
      return translation.replace(/\{\{(\w+)\}\}/g, (match, param) => {
        return params[param] !== undefined ? params[param] : match
      })
    }

    return translation
  }

  return {
    locale,
    setLocale,
    t,
  }
}
