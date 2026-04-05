import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { getCryptoIconUrl, getChainIconUrl, getChainDisplayName } from "@/lib/cryptoIcons"
import { useI18n } from "@/hooks/useI18n"

function InvoiceCard({ invoice }) {
  const { t } = useI18n()

  if (!invoice) return null

  const hasPayMethod = Boolean(
    invoice.crypto && invoice.chain && invoice.pay_address && invoice.pay_amount
  )

  const getStatusStyle = (status) => {
    switch (status) {
      case "waiting":
        return {
          dot: "bg-blue-400 animate-pulse",
          badge: "bg-blue-500/10 text-blue-300 border border-blue-500/20",
        }
      case "confirming":
        return {
          dot: "bg-amber-400 animate-pulse",
          badge: "bg-amber-500/10 text-amber-300 border border-amber-500/20",
        }
      case "completed":
        return {
          dot: "bg-emerald-400",
          badge: "bg-emerald-500/10 text-emerald-300 border border-emerald-500/20",
        }
      case "expired":
        return {
          dot: "bg-slate-600",
          badge: "bg-slate-500/10 text-slate-500 border border-slate-500/20",
        }
      default:
        return {
          dot: "bg-slate-600",
          badge: "bg-slate-500/10 text-slate-500 border border-slate-500/20",
        }
    }
  }

  const statusStyle = getStatusStyle(invoice.status)

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1">
            <CardTitle className="text-white text-lg">{t("invoice.title")}</CardTitle>
            <CardDescription className="text-slate-500 text-sm mt-1.5">
              {t("invoice.orderNumber")}:{" "}
              <span className="font-mono text-slate-400">{invoice.out_no}</span>
            </CardDescription>
          </div>
          <span
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${statusStyle.badge}`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${statusStyle.dot}`} />
            {t(`invoice.status.${invoice.status}`) || t("invoice.status.unknown")}
          </span>
        </div>
      </CardHeader>

      <CardContent className="space-y-5">
        {/* Invoice title */}
        <div className="pb-4 border-b border-white/[0.06]">
          <h3 className="text-sm font-semibold text-white">{invoice.title}</h3>
          <p className="text-xs text-slate-600 mt-1 font-mono">
            {t("invoice.systemNumber")}: {invoice.sys_no}
          </p>
        </div>

        {/* Amount due */}
        <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-5">
          <div className="text-xs font-semibold text-slate-600 uppercase tracking-widest mb-3">
            {t("invoice.amountDue")}
          </div>
          <div className="flex items-baseline justify-between">
            <div>
              <div className="text-3xl font-bold text-white tabular-nums">{invoice.amount}</div>
              <div className="text-sm font-medium text-slate-500 mt-0.5">{invoice.currency}</div>
            </div>
            {hasPayMethod && (
              <div className="text-right">
                <div className="text-lg font-semibold text-orange-400 font-mono tabular-nums">
                  {invoice.pay_amount}
                </div>
                <div className="text-xs text-slate-500 mt-0.5 font-mono">{invoice.crypto}</div>
              </div>
            )}
          </div>
        </div>

        {/* Payment method info */}
        {hasPayMethod && (
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-white/[0.03] rounded-xl p-3 border border-white/[0.06]">
              <div className="text-xs font-medium text-slate-600 mb-2">
                {t("invoice.paymentToken")}
              </div>
              <div className="flex items-center gap-2 mt-2">
                <img
                  src={getCryptoIconUrl(invoice.crypto)}
                  alt={invoice.crypto}
                  className="w-6 h-6 rounded-full"
                  onError={(e) => {
                    e.target.style.display = "none"
                  }}
                />
                <span className="font-semibold text-white text-sm">{invoice.crypto}</span>
              </div>
            </div>
            <div className="bg-white/[0.03] rounded-xl p-3 border border-white/[0.06]">
              <div className="text-xs font-medium text-slate-600 mb-2">
                {t("invoice.blockchainNetwork")}
              </div>
              <div className="flex items-center gap-2 mt-2">
                <img
                  src={getChainIconUrl(invoice.chain)}
                  alt={invoice.chain}
                  className="w-6 h-6 rounded-full"
                  onError={(e) => {
                    e.target.style.display = "none"
                  }}
                />
                <span className="font-semibold text-white text-sm">
                  {getChainDisplayName(invoice.chain)}
                </span>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default InvoiceCard
