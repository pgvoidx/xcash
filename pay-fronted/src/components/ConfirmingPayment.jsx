import { Card, CardContent } from "@/components/ui/card"
import { useI18n } from "@/hooks/useI18n"

/**
 * 等待支付确认组件 - confirming 状态
 * 用户已付款,等待区块链确认
 */
function ConfirmingPayment() {
  const { t } = useI18n()

  return (
    <Card className="animate-in fade-in-0 slide-in-from-bottom-4 duration-500">
      <CardContent className="pt-6">
        <div className="flex flex-col items-center space-y-4">
          {/* 加载图标 */}
          <div className="w-12 h-12 rounded-full border-2 border-slate-200 border-t-slate-600 animate-spin" />

          <div className="text-center">
            <p className="font-medium text-slate-900">{t("payment.paymentConfirming")}</p>
            <p className="text-sm text-slate-500 mt-1">{t("confirmation.waitingConfirmation")}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export default ConfirmingPayment
