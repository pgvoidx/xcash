// src/components/StepInvoice.jsx
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/hooks/useI18n"

function StepInvoice({ invoice, onConfirm, isExpired, isSingleMethod }) {
  const { t } = useI18n()

  return (
    <div className="space-y-4 animate-in fade-in-0 slide-in-from-bottom-2 duration-300">
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div className="flex-1">
              <CardTitle className="text-lg">{t("invoice.title")}</CardTitle>
              <CardDescription className="text-slate-500 text-sm mt-1.5">
                {t("invoice.orderNumber")}:{" "}
                <span className="font-mono text-slate-400">{invoice.out_no}</span>
              </CardDescription>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-5">
          {/* Title */}
          <div className="pb-4 border-b border-border">
            <h3 className="text-sm font-semibold text-card-foreground">{invoice.title}</h3>
            <p className="text-xs text-slate-600 mt-1 font-mono">
              {t("invoice.systemNumber")}: {invoice.sys_no}
            </p>
          </div>

          {/* Amount */}
          <div className="bg-background/40 dark:bg-white/[0.03] border border-border rounded-xl p-5">
            <div className="text-xs font-semibold text-slate-600 uppercase tracking-widest mb-3">
              {t("invoice.amountDue")}
            </div>
            <div className="text-3xl font-bold text-card-foreground tabular-nums">
              {invoice.amount}
            </div>
            <div className="text-sm font-medium text-slate-500 mt-1">{invoice.currency}</div>
          </div>
        </CardContent>
      </Card>

      {/* CTA — hidden when expired */}
      {!isExpired && (
        <>
          <Button
            onClick={onConfirm}
            className="w-full font-semibold text-sm py-5 shadow-[0_0_24px_rgba(249,115,22,0.2)] hover:shadow-[0_0_32px_rgba(249,115,22,0.3)] transition-all duration-200 cursor-pointer"
          >
            {isSingleMethod
              ? (t("payment.confirmAndPay") || "确认并支付账单 →")
              : (t("payment.confirmAndSelectMethod") || "确认并选择支付方式 →")
            }
          </Button>
          <p className="text-xs text-slate-700 text-center px-4">
            {t("invoice.paymentIrreversible") || "请仔细核对金额与订单信息，支付后无法撤销"}
          </p>
        </>
      )}

      {/* Expired */}
      {isExpired && (
        <Card>
          <CardContent className="text-center space-y-5 py-8">
            <div className="w-14 h-14 mx-auto bg-red-500/10 border border-red-500/20 rounded-full flex items-center justify-center">
              <svg className="w-7 h-7 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M12 8v4m0 6h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div>
              <h3 className="font-semibold text-card-foreground mb-1">{t("expired.orderExpired")}</h3>
              <p className="text-sm text-slate-500">{t("expired.contactMerchant")}</p>
            </div>
            <Button
              onClick={() => window.location.reload()}
              variant="ghost"
              className="w-full border border-white/[0.08] text-slate-400 hover:bg-white/[0.06] hover:text-slate-300 cursor-pointer"
            >
              {t("expired.refreshPage")}
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

export default StepInvoice
