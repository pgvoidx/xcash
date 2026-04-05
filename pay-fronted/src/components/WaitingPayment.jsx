import { useEffect, useState, useMemo } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { useI18n } from "@/hooks/useI18n"

/**
 * 格式化剩余时间
 */
const formatRemainingTime = (remainingMs, t) => {
  if (remainingMs === null || typeof remainingMs === "undefined") {
    return "--:--:--"
  }

  const totalSeconds = Math.floor(remainingMs / 1000)
  const days = Math.floor(totalSeconds / 86400)
  const hours = Math.floor((totalSeconds % 86400) / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60

  const pad = (value) => value.toString().padStart(2, "0")

  if (days > 0) {
    return `${days}${t("waiting.days")} ${pad(hours)}:${pad(minutes)}:${pad(seconds)}`
  }

  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`
}

/**
 * 获取剩余时间(毫秒)
 */
const getRemainingMs = (expiresAt) => {
  if (!expiresAt) return null
  const expireTimestamp = new Date(expiresAt).getTime()
  if (Number.isNaN(expireTimestamp)) return null
  return Math.max(0, expireTimestamp - Date.now())
}

/**
 * 等待支付组件 - waiting 状态
 * 用户还未付款,显示倒计时
 */
function WaitingPayment({ invoice, onExpired }) {
  const { t } = useI18n()
  const [remainingMs, setRemainingMs] = useState(() => getRemainingMs(invoice?.expires_at))

  // 更新倒计时
  useEffect(() => {
    if (!invoice?.expires_at) {
      setRemainingMs(null)
      return
    }

    const updateRemaining = () => {
      setRemainingMs(getRemainingMs(invoice.expires_at))
    }

    updateRemaining()
    const timer = setInterval(updateRemaining, 1000)

    return () => clearInterval(timer)
  }, [invoice?.expires_at])

  // 倒计时归零时立即刷新账单状态，避免用户看到 "expired" 文字却页面不变
  useEffect(() => {
    if (remainingMs === 0 && onExpired) {
      onExpired()
    }
  }, [remainingMs, onExpired])

  // 倒计时颜色
  const countdownTone = useMemo(() => {
    if (remainingMs === null) return "text-amber-400"
    if (remainingMs <= 0) return "text-red-400"
    if (remainingMs <= 60_000) return "text-red-400"
    if (remainingMs <= 5 * 60_000) return "text-amber-400"
    return "text-emerald-400"
  }, [remainingMs])

  const countdownText = useMemo(() => formatRemainingTime(remainingMs, t), [remainingMs, t])

  return (
    <Card className="animate-in fade-in-0 slide-in-from-bottom-4 duration-500">
      <CardContent className="pt-6">
        <div className="flex flex-col items-center space-y-4">
          {/* Pulsing orange ring */}
          <div className="relative w-12 h-12 flex items-center justify-center">
            <div className="absolute inset-0 rounded-full border-2 border-orange-500/20 animate-ping" />
            <div className="w-12 h-12 rounded-full border-2 border-orange-500/30 border-t-orange-500 animate-spin" />
          </div>

          <div className="text-center">
            <p className="font-medium text-white">{t("waiting.title")}</p>
            <p className="text-sm text-slate-500 mt-1">{t("waiting.description")}</p>
          </div>

          {/* Countdown */}
          {invoice?.expires_at && (
            <div className="w-full bg-white/[0.03] rounded-xl p-3 border border-white/[0.06]">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-slate-500">
                  {t("waiting.timeRemaining")}
                </span>
                <span className={`font-mono font-bold text-base tabular-nums ${countdownTone}`}>
                  {remainingMs === 0 ? t("waiting.expired") : countdownText}
                </span>
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

export default WaitingPayment
