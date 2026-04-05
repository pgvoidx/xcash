import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { getCryptoIconUrl, getCryptoDisplayName } from "@/lib/cryptoIcons"
import { useI18n } from "@/hooks/useI18n"

function TokenSelector({ availableMethods, selectedCrypto, onCryptoChange, disabled = false }) {
  const { t } = useI18n()

  if (!availableMethods || Object.keys(availableMethods).length === 0) {
    return (
      <div className="p-4 border border-dashed border-white/[0.08] rounded-xl text-center bg-white/[0.02]">
        <p className="text-sm text-slate-600">{t("selector.noTokens")}</p>
      </div>
    )
  }

  const tokenOptions = Object.keys(availableMethods)

  return (
    <Select value={selectedCrypto} onValueChange={onCryptoChange} disabled={disabled}>
      <SelectTrigger className="h-12 text-left bg-white/[0.04] border-white/[0.1] text-white hover:bg-white/[0.07] focus:ring-orange-500/30 focus:border-orange-500/40 transition-colors shadow-none cursor-pointer">
        <SelectValue
          placeholder={
            <div className="flex items-center space-x-2 text-slate-500">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1"
                />
              </svg>
              <span>{t("selector.selectToken")}</span>
            </div>
          }
        />
      </SelectTrigger>
      <SelectContent className="bg-[#0D1524] border-white/[0.1] shadow-2xl shadow-black/60">
        {tokenOptions.map((token) => (
          <SelectItem
            key={token}
            value={token}
            className="cursor-pointer text-white hover:bg-white/[0.06] focus:bg-white/[0.06] focus:text-white"
          >
            <div className="flex items-center space-x-3">
              <img
                src={getCryptoIconUrl(token)}
                alt={token}
                className="w-8 h-8 rounded-full"
                onError={(e) => {
                  e.target.style.display = "none"
                  e.target.nextElementSibling.style.display = "flex"
                }}
              />
              <div
                className="w-8 h-8 rounded-full bg-gradient-to-br from-orange-500 to-amber-600 items-center justify-center hidden"
              >
                <span className="text-white text-xs font-bold">{token.substring(0, 2)}</span>
              </div>
              <div>
                <p className="font-medium text-white">{getCryptoDisplayName(token)}</p>
                <p className="text-xs text-slate-500">
                  {availableMethods[token].length} {t("selector.networks")}
                </p>
              </div>
            </div>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export default TokenSelector
