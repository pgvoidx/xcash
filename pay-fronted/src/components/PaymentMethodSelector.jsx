import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Check } from "lucide-react"
import TokenSelector from "@/components/TokenSelector"
import ChainSelector from "@/components/ChainSelector"
import { useI18n } from "@/hooks/useI18n"

function PaymentMethodSelector({
  availableMethods,
  selectedCrypto,
  selectedChain,
  onCryptoChange,
  onChainChange,
  isSelecting,
  isEditing,
  error,
  onCancelEdit,
}) {
  const { t } = useI18n()

  return (
    <div className="space-y-1">
      {/* Title */}
      <div className="mb-4">
        <h2 className="text-base font-semibold text-card-foreground">{t("payment.selectMethod")}</h2>
        <p className="text-xs text-muted-foreground mt-0.5">{t("payment.selectMethodDesc")}</p>
      </div>

      {/* Step 1: Token */}
      <Card className={`transition-all duration-200 ${selectedCrypto ? "border-orange-500/30" : ""}`}>
        <CardContent className="p-4">
          <div className="flex items-start gap-3 mb-3">
            <div className={`mt-0.5 w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 transition-all duration-300 ${
              selectedCrypto
                ? "bg-orange-500 text-white shadow-[0_0_12px_rgba(249,115,22,0.35)]"
                : "bg-black/[0.06] dark:bg-white/[0.06] text-muted-foreground border border-black/[0.1] dark:border-white/[0.1]"
            }`}>
              {selectedCrypto
                ? <Check className="w-3.5 h-3.5" />
                : <span className="text-[11px] font-bold">1</span>
              }
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-card-foreground">{t("payment.selectToken")}</span>
                {selectedCrypto && (
                  <span className="text-xs font-semibold text-orange-500 bg-orange-500/10 px-2 py-0.5 rounded-full flex-shrink-0">
                    {selectedCrypto}
                  </span>
                )}
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">{t("payment.selectTokenDesc")}</p>
            </div>
          </div>
          <TokenSelector
            availableMethods={availableMethods}
            selectedCrypto={selectedCrypto}
            onCryptoChange={onCryptoChange}
            disabled={isSelecting}
          />
        </CardContent>
      </Card>

      {/* Connector */}
      <div className="flex justify-center py-0.5">
        <div className={`w-px h-5 transition-colors duration-300 ${selectedCrypto ? "bg-orange-500/40" : "bg-border"}`} />
      </div>

      {/* Step 2: Network */}
      <Card className={`transition-all duration-200 ${
        selectedChain ? "border-orange-500/30" : !selectedCrypto ? "opacity-50" : ""
      }`}>
        <CardContent className="p-4">
          <div className="flex items-start gap-3 mb-3">
            <div className={`mt-0.5 w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 transition-all duration-300 ${
              selectedChain
                ? "bg-orange-500 text-white shadow-[0_0_12px_rgba(249,115,22,0.35)]"
                : selectedCrypto
                  ? "bg-black/[0.06] dark:bg-white/[0.06] text-muted-foreground border border-black/[0.1] dark:border-white/[0.1]"
                  : "bg-black/[0.03] dark:bg-white/[0.03] text-muted-foreground/40 border border-black/[0.06] dark:border-white/[0.05]"
            }`}>
              {selectedChain
                ? <Check className="w-3.5 h-3.5" />
                : <span className="text-[11px] font-bold">2</span>
              }
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-card-foreground">{t("payment.selectNetwork")}</span>
                {selectedChain && (
                  <span className="text-xs font-semibold text-orange-500 bg-orange-500/10 px-2 py-0.5 rounded-full flex-shrink-0">
                    {selectedChain}
                  </span>
                )}
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">{t("payment.selectNetworkDesc")}</p>
            </div>
          </div>
          <ChainSelector
            availableMethods={availableMethods}
            selectedCrypto={selectedCrypto}
            selectedChain={selectedChain}
            onChainChange={onChainChange}
            disabled={isSelecting}
          />
        </CardContent>
      </Card>

      {/* Loading */}
      {isSelecting && (
        <div className="mt-2 text-center py-4 bg-background/40 dark:bg-white/[0.03] rounded-xl border border-border">
          <div className="flex items-center justify-center gap-2.5">
            <div className="animate-spin rounded-full h-4 w-4 border-2 border-orange-500/30 border-t-orange-500" />
            <p className="text-sm font-medium text-muted-foreground">{t("payment.gettingPaymentInfo")}</p>
          </div>
        </div>
      )}

      {/* Error */}
      {error && !isSelecting && (
        <div className="mt-2 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20">
          <p className="text-sm text-red-400">{error}</p>
        </div>
      )}

      {/* Cancel edit */}
      {isEditing && !isSelecting && (
        <div className="flex justify-end pt-1">
          <Button
            variant="ghost"
            onClick={onCancelEdit}
            size="sm"
            className="text-muted-foreground hover:text-foreground hover:bg-black/[0.05] dark:hover:bg-white/[0.06] cursor-pointer"
          >
            {t("common.cancel")}
          </Button>
        </div>
      )}
    </div>
  )
}

export default PaymentMethodSelector
