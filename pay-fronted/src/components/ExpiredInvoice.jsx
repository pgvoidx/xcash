import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/hooks/useI18n"

/**
 * 账单超时组件
 */
function ExpiredInvoice() {
  const { t } = useI18n()

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-white text-lg">{t("expired.title")}</CardTitle>
      </CardHeader>
      <CardContent className="text-center space-y-5">
        <div className="w-16 h-16 mx-auto bg-red-500/10 border border-red-500/20 rounded-full flex items-center justify-center">
          <svg
            className="w-8 h-8 text-red-400"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 8v4m0 6h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
        </div>
        <div>
          <h3 className="font-semibold text-white mb-1">{t("expired.orderExpired")}</h3>
          <p className="text-sm text-slate-500">{t("expired.contactMerchant")}</p>
        </div>
        <Button
          onClick={() => window.location.reload()}
          variant="ghost"
          className="w-full border border-white/[0.08] text-slate-400 hover:bg-white/[0.06] hover:text-slate-300 hover:border-white/[0.15] cursor-pointer"
        >
          {t("expired.refreshPage")}
        </Button>
      </CardContent>
    </Card>
  )
}

export default ExpiredInvoice
